#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一副牌升级 · Web 版 — Flask 后端（1:1 包装 game.py 引擎，效果与 gui.py 一致）

状态机:
  idle → trump → bury → pick → playing → settled → (next round or finish)
  playing 内部有 reveal 子阶段: 逐玩家揭示出牌动画

关键: step() 每次推进一个"视觉步骤"，与 gui.py 的 _do_one_step 完全对齐。
"""

import sys
import os
import json
import random
import time
from flask import Flask, render_template, jsonify, request, send_file

sys.path.insert(0, os.path.dirname(__file__))

from game import (
    create_deck, Card, Bot, RoundRecord,
    SUITS, SUIT_CN, SCORE_RANKS, SCORE_VALUES, RANK_ORDER,
    cp, is_main, cards_str,
    compare_trick_patterns,
    level_up,
    check_deal_requirements,
    LEVEL_CYCLE, save_excel,
    Game
)
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from datetime import datetime
import io

app = Flask(__name__, template_folder='web/templates', static_folder='web/static')
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

# ==================== 会话管理 ====================

sessions = {}
SESSION_TTL = 1800
MAX_RECORDS = 1000      # 单会话对局记录(局)上限


def _cleanup_sessions():
    now = time.time()
    expired = [sid for sid, s in sessions.items() if now - s._last_access > SESSION_TTL]
    for sid in expired:
        sessions.pop(sid, None)


class WebSession:
    """包装 Game 引擎的 Web 会话 — 1:1 复刻 gui.py 的 GameGUI 逻辑"""

    def __init__(self, seed=None, total_rounds=None, deal_requirements=None):
        self.seed = seed if seed is not None else random.randint(1, 999999)
        random.seed(self.seed)

        # === 游戏状态（同 GameGUI.__init__）===
        self.running = False
        self.step_mode = True
        self.step_delay = 400
        self.total_rounds = total_rounds
        self.deal_requirements = deal_requirements or {}

        # 当前局数据
        self.rec = None
        self.hands = None
        self.bottom = None
        self.bots = {}
        self.trick_idx = 0
        self.current_trick = None
        self.dt = []
        self.at = []

        # 引擎状态
        self.engine_state = None
        self._reveal_count = None
        self._pending_trick = None

        self.dealer_pid = random.randint(0, 3)
        self.defender_level = '7'
        self.attacker_level = '7'
        self._next_defender_level = '7'
        self._next_attacker_level = '7'
        self.team_a_level = '7'
        self.team_b_level = '7'
        self.team_a_cumulative_steps = 0
        self.team_b_cumulative_steps = 0
        self.defending_team = None
        self.records = []
        self.round_records = []
        self.current_round = 1
        self.round_starts_at = 1
        self.rnd = 0
        self.game_over_flag = False
        self.winner = None
        self.limit_reached = False          # 对局记录数达上限后冻结(需重置才能继续)

        self._last_access = time.time()
        self._last_status = "就绪 | 点击「开始」启动游戏"

        # === 回放时间线（参考三副牌 v1.2）===
        self._timeline = []          # 每步快照 (序列化 dict) 的完整时间线
        self._view = 0               # 当前显示位置 (0..live_steps)
        self._live_steps = 0         # 引擎已执行步数
        self._round_start_step = {}  # rnd -> 该局"初始快照"在时间线中的下标

    # ==================== 序列化辅助 ====================

    def _card_to_dict(self, card):
        if card is None:
            return None
        return {'suit': card.suit, 'rank': card.rank}

    def _cards_to_dicts(self, cards):
        if cards is None:
            return []
        return [self._card_to_dict(c) for c in cards]

    def _card_str(self, card):
        """单张牌显示文本: 普通牌 '♠9'，大小王 '大王/小王'"""
        if card is None:
            return '—'
        if card.rank in ('大王', '小王'):
            return card.rank
        return f"{card.suit}{card.rank}"

    def _cards_str(self, cards):
        return ' '.join(self._card_str(c) for c in cards) if cards else '—'

    def _trick_event(self, trick):
        """整圈的 文字记录 事件 — 含四家出牌明细"""
        plays = [{'pid': pid, 'cards': self._cards_to_dicts(cl),
                  'text': f"玩{pid + 1}: {self._cards_str(cl)}"}
                 for pid, cl in trick['played']]
        win = trick.get('winner')
        side = '庄' if trick.get('winner_side') == 'dealer' else '闲'
        wtext = f"玩家{win + 1}" if win is not None else '?'
        return {
            'type': 'trick', 'num': trick['num'], 'leader': trick.get('leader'),
            'plays': plays, 'winner': win, 'winner_side': trick.get('winner_side'),
            'score': trick.get('score', 0),
            'text': f"第 {trick['num']} 圈 | {' | '.join(p['text'] for p in plays)} "
                    f"| 赢: {wtext}({side} +{trick.get('score', 0)}分)",
        }

    # ==================== 发牌 ====================

    def _deal(self):
        reqs = self.deal_requirements
        for attempt in range(100000):
            deck = create_deck()
            random.shuffle(deck)
            hands = [[] for _ in range(4)]
            bottom = []
            for i, card in enumerate(deck):
                (hands[i % 4] if i < 48 else bottom).append(card)
            if not reqs or check_deal_requirements(hands, reqs):
                self.hands = hands
                self.bottom = bottom
                self.rec.initial_hands = {p: list(h) for p, h in enumerate(hands)}
                self.rec.initial_bottom = list(bottom)
                return
        self.hands = hands
        self.bottom = bottom
        self.rec.initial_hands = {p: list(h) for p, h in enumerate(hands)}
        self.rec.initial_bottom = list(bottom)

    # ==================== 定主 ====================

    def _do_trump_stage(self):
        rec = self.rec
        dt, at = self.dt, self.at
        lvl = rec.level

        for pid in range(4):
            lc = [c for c in self.hands[pid] if c.rank == lvl and c.suit in SUITS]
            if lc and random.random() < 0.25:
                card = random.choice(lc)
                rec.concealed_pid, rec.concealed_card = pid, card
                rec.trump_method = 'concealed'
                break
        else:
            for pid in dt:
                lc = [c for c in self.hands[pid] if c.rank == lvl and c.suit in SUITS]
                if lc and random.random() < 0.5:
                    card = random.choice(lc)
                    rec.bright_pid, rec.bright_card = pid, card
                    rec.trump_suit, rec.trump_method = card.suit, 'bright'
                    break
            else:
                for pid in at:
                    lc = [c for c in self.hands[pid] if c.rank == lvl and c.suit in SUITS]
                    if lc and random.random() < 0.5:
                        card = random.choice(lc)
                        rec.concealed_pid, rec.concealed_card = pid, card
                        rec.trump_method = 'concealed'
                        break
                else:
                    fc = next((c for c in rec.initial_bottom if c.suit in SUITS), None)
                    rec.trump_suit = fc.suit if fc else random.choice(SUITS)
                    rec.trump_method = 'bottom_card'
                    rec.bottom_trump_card = fc

        # 闷牌→亮牌（庄家方）
        if rec.trump_method == 'concealed' and rec.concealed_pid is not None \
                and rec.concealed_pid in dt:
            rec.bright_pid = rec.concealed_pid
            rec.bright_card = rec.concealed_card
            rec.trump_suit = rec.concealed_card.suit
            rec.trump_method = 'bright'
            rec.concealed_pid = None
            rec.concealed_card = None

        self.engine_state = 'bury'
        label = self._trump_label()
        self._set_status(label)
        rec.events.append({
            'type': 'trump', 'method': rec.trump_method, 'suit': rec.trump_suit,
            'bright_pid': rec.bright_pid, 'bright_card': self._card_to_dict(rec.bright_card),
            'concealed_pid': rec.concealed_pid,
            'concealed_card': self._card_to_dict(rec.concealed_card) if rec.concealed_card else None,
            'text': label,
        })

    def _trump_label(self):
        rec = self.rec
        if rec.trump_method == 'bright':
            return f"⭐ 亮牌定主: 玩{rec.bright_pid + 1}亮{rec.bright_card} → {SUIT_CN.get(rec.trump_suit, '')}"
        elif rec.trump_method == 'concealed':
            return f"🃏 闷牌: 玩{rec.concealed_pid + 1}暗扣级牌（花色待揭晓）"
        return f"🎲 底牌首张定主 → {SUIT_CN.get(rec.trump_suit, '')}"

    # ==================== 埋底 ====================

    def _do_bury_stage(self):
        rec = self.rec
        pid = self.dealer_pid
        bottom = list(rec.initial_bottom)
        bot = Bot(pid, self.hands[pid], 'dealer', rec.level, rec.trump_suit or '')
        n = random.randint(0, 6)
        buried = bot.select_for_bottom(n)
        temp_bottom = bottom + buried
        score = sum(SCORE_VALUES.get(c.rank, 0) for c in temp_bottom)
        for _ in range(10):
            if score <= 35:
                break
            sc = [c for c in buried if c.rank in SCORE_RANKS]
            if not sc:
                break
            buried.remove(sc[0])
            bot.hand.append(sc[0])
            temp_bottom = bottom + buried
            score = sum(SCORE_VALUES.get(c.rank, 0) for c in temp_bottom)
        take_back = temp_bottom[:len(buried)]
        new_bottom = temp_bottom[len(buried):]
        bot.hand.extend(take_back)
        self.hands[pid] = bot.hand
        rec.buried_cards = list(buried)
        rec.bottom_after_bury = list(new_bottom)
        self.bottom = list(new_bottom)
        bs = sum(SCORE_VALUES.get(c.rank, 0) for c in new_bottom)
        self._set_status(f"📦 埋底完成 | 庄家埋{len(buried)}张取回{len(take_back)}张 | 底牌{bs}分")
        rec.events.append({
            'type': 'bury', 'pid': pid,
            'buried': self._cards_to_dicts(buried),
            'take_back': self._cards_to_dicts(take_back),
            'text': f"📦 埋底: 玩{pid + 1} 埋 {len(buried)} 张取回 {len(take_back)} 张 | 底牌 {bs} 分",
        })

        if rec.concealed_pid is not None:
            self.engine_state = 'pick'
        else:
            self._finalize_prep()

    # ==================== 捡主 ====================

    def _do_pick_stage(self):
        rec = self.rec
        pid = rec.concealed_pid
        ts = rec.concealed_card.suit
        rec.trump_suit = ts
        bottom = list(rec.bottom_after_bury)
        bot = Bot(pid, self.hands[pid], 'attacker', rec.level, ts)
        picked = [c for c in bottom if is_main(c, rec.level, ts)]
        if picked:
            rec.picked_from_bottom = list(picked)
            bottom_rem = [c for c in bottom if c not in picked]
            bot.hand.extend(picked)
            discarded = bot.select_for_bottom(len(picked))
            new_bottom = bottom_rem + discarded
            new_bs = sum(SCORE_VALUES.get(c.rank, 0) for c in new_bottom)
            if new_bs <= 35:
                self.hands[pid] = list(bot.hand)
                rec.discarded_to_bottom = list(discarded)
                rec.bottom_after_pick = list(new_bottom)
                self.bottom = list(new_bottom)
                msg = f"🔍 捡主: 玩{pid + 1}翻开{rec.concealed_card} → {SUIT_CN.get(ts, '')}"
                self._set_status(msg)
            else:
                msg = f"⚠️ 捡主后底牌{new_bs}分>35，放弃捡主"
                self._set_status(msg)
        else:
            msg = f"🔍 捡主: 底牌无主牌，跳过"
            self._set_status(msg)
        rec.events.append({
            'type': 'pick', 'pid': pid, 'trump_suit': ts,
            'picked': self._cards_to_dicts(rec.picked_from_bottom),
            'discarded': self._cards_to_dicts(rec.discarded_to_bottom),
            'text': msg,
        })

        self._finalize_prep()

    # ==================== 准备出牌 ====================

    def _finalize_prep(self):
        rec = self.rec
        for pid in range(4):
            assert len(self.hands[pid]) == 12
        dt, at = self.dt, self.at
        self.bots = {}
        for pid in range(4):
            side = 'dealer' if pid in dt else 'attacker'
            self.bots[pid] = Bot(pid, self.hands[pid], side, rec.level, rec.trump_suit)
        self.trick_leader = self.dealer_pid
        self.trick_idx = 0
        self.current_trick = None
        rec.tricks = []
        self.engine_state = 'playing'
        self._set_status(f"开始出牌 | 主花色={SUIT_CN.get(rec.trump_suit, '')}")

    # ==================== 出牌（逐玩家揭示动画）====================

    def _play_next_trick(self):
        """播放下一圈 — 1:1 复刻 gui._play_next_trick + _reveal_next_card"""
        # 动画进行中则推进动画
        if self._reveal_count is not None:
            self._reveal_next_card()
            return

        if self.trick_idx >= 12:
            self._settle_and_continue()
            return

        dt, at = self.dt, self.at
        rec = self.rec
        bots = self.bots

        if not all(bots[p].hand for p in range(4)):
            self._settle_and_continue()
            return

        t = self.trick_idx + 1
        trick = {'num': t, 'leader': self.trick_leader, 'played': [], 'winner': None,
                 'winner_side': None, 'score': 0, 'score_cards': [], 'pattern': 'single'}
        lead_suit = None
        played_so_far = []

        for pos in range(4):
            pid = (self.trick_leader + pos) % 4
            if pos == 0:
                card_list = bots[pid].lead()
                lead_suit = card_list[0].suit if card_list else None
            else:
                card_list = bots[pid].follow(lead_suit, played_so_far)
            trick['played'].append((pid, card_list))
            played_so_far.append((pid, card_list))

        if not any(cl for _, cl in trick['played']):
            return

        first_cards = played_so_far[0][1] if played_so_far else []
        if first_cards:
            trick['pattern'] = bots[played_so_far[0][0]]._detect_pattern(first_cards)

        best_pid = None
        best_pattern = None
        best_cards = None
        for pid, card_list in trick['played']:
            if not card_list:
                continue
            p = bots[pid]._detect_pattern(card_list)
            if best_pid is None:
                best_pid, best_pattern, best_cards = pid, p, card_list
            else:
                cmp = compare_trick_patterns(p, card_list, best_pattern, best_cards,
                                             rec.level, rec.trump_suit, lead_suit)
                if cmp == 1:
                    best_pid, best_pattern, best_cards = pid, p, card_list

        trick['winner'] = best_pid
        trick['winner_side'] = 'dealer' if best_pid in dt else 'attacker'
        trick['winner_pattern'] = best_pattern
        for pid, card_list in trick['played']:
            for card in card_list:
                if card.rank in SCORE_RANKS:
                    trick['score_cards'].append(card)
                    trick['score'] += SCORE_VALUES[card.rank]

        rec.tricks.append(trick)
        self.trick_idx = t

        # 手牌已空则直接结算
        if any(len(bots[p].hand) == 0 for p in range(4)):
            self.current_trick = trick
            self.trick_leader = best_pid
            rec.events.append(self._trick_event(trick))
            self._settle_and_continue()
            return

        # 启动逐张揭示动画
        self._pending_trick = trick
        self._reveal_count = 0
        self._reveal_next_card()

    def _reveal_next_card(self):
        """逐玩家揭示出牌 — 1:1 复刻 gui._reveal_next_card"""
        self._reveal_count += 1
        trick = self._pending_trick

        # 设置已揭示的牌
        revealed = trick['played'][:self._reveal_count]
        self.current_trick = {**trick, 'played': revealed}

        if self._reveal_count >= 4:
            self._reveal_count = None
            self._pending_trick = None
            self.trick_leader = trick['winner']
            self.rec.events.append(self._trick_event(trick))

            if any(len(self.bots[p].hand) == 0 for p in range(4)):
                self._settle_and_continue()
                return

            self._set_status(
                f"第 {self.rnd} 局 | 第 {trick['num']} 圈 | 赢家: 玩家{trick['winner'] + 1} (+{trick['score']}分)")
            return

    # ==================== 结算 ====================

    def _settle_and_continue(self):
        self.engine_state = 'settled'
        rec = self.rec
        sc = sum(tr['score'] for tr in rec.tricks)
        rec.attacker_score = sc
        if rec.tricks:
            lt = rec.tricks[-1]
            rec.last_trick_winner_pid = lt['winner']
            rec.last_trick_winner_side = lt['winner_side']
            for pid, cl in lt['played']:
                if pid == lt['winner']:
                    rec.last_trick_card = cl[-1] if cl else None
                    break

        # 结算升级
        is_bottom = rec.last_trick_winner_side == 'attacker'
        if sc == 0:
            rec.base_up_att = 0
            rec.final_up_def = 3
        elif sc <= 35:
            rec.base_up_att = 0
            rec.final_up_def = 1
        elif sc <= 39:
            rec.base_up_att = 0
            rec.final_up_def = 0
        elif sc <= 45:
            rec.base_up_att = 0
            rec.final_up_def = 0
        else:
            rec.base_up_att = min((sc - 50) // 10 + 1, 6)
            rec.final_up_def = 0

        bonus = 0
        if is_bottom:
            bonus = 4 if (rec.last_trick_card and rec.last_trick_card.rank == '大王') else 3
        rec.bonus_up = bonus
        if is_bottom and sc < 40:
            rec.final_up_def = 0
            rec.base_up_att = 0
            rec.bonus_up = 0
        rec.final_up_att = rec.base_up_att + bonus

        # 等级更新
        if self.dealer_pid in (0, 2):
            self.team_a_cumulative_steps += rec.final_up_def
            self.team_b_cumulative_steps += rec.final_up_att
            self.team_a_level = level_up(self.team_a_level, rec.final_up_def)
            self.team_b_level = level_up(self.team_b_level, rec.final_up_att)
        else:
            self.team_b_cumulative_steps += rec.final_up_def
            self.team_a_cumulative_steps += rec.final_up_att
            self.team_b_level = level_up(self.team_b_level, rec.final_up_def)
            self.team_a_level = level_up(self.team_a_level, rec.final_up_att)

        new_def = level_up(self.defender_level, rec.final_up_def)
        new_att = level_up(self.attacker_level, rec.final_up_att)

        if rec.final_up_att > 0 or (40 <= sc <= 45):
            self._next_defender_level = new_att
            self._next_attacker_level = new_def
        else:
            self._next_defender_level = new_def
            self._next_attacker_level = new_att

        # 过7判定
        dealer_is_a = self.dealer_pid in (0, 2)
        dealer_steps = self.team_a_cumulative_steps if dealer_is_a else self.team_b_cumulative_steps
        attacker_steps = self.team_b_cumulative_steps if dealer_is_a else self.team_a_cumulative_steps
        dlabel = '队伍A' if dealer_is_a else '队伍B'
        alabel = '队伍B' if dealer_is_a else '队伍A'

        if dealer_steps >= len(LEVEL_CYCLE):
            rec.result_title = f'{dlabel}过7🏆'
            rec.round_ended = True
            rec.round_winner = dlabel
            if not self.total_rounds:
                self.game_over_flag = True
                self.winner = f'{dlabel}（庄家方）'
            else:
                self._reset_round_state()
        elif attacker_steps >= len(LEVEL_CYCLE):
            self._reset_round_state()
            new_dealer = (self.dealer_pid + 1) % 4 if self.dealer_pid % 2 == 0 else (self.dealer_pid + 3) % 4
            self.dealer_pid = new_dealer
            rec.result_title = f'{alabel}过7🏆'
            rec.round_ended = True
            rec.round_winner = alabel
            self._next_defender_level = '7'
            self._next_attacker_level = '7'
        elif rec.final_up_att > 0 or (40 <= sc <= 45):
            new_dealer = (self.dealer_pid + 1) % 4 if self.dealer_pid % 2 == 0 else (self.dealer_pid + 3) % 4
            self.dealer_pid = new_dealer
            self._next_defender_level = new_att
            self._next_attacker_level = new_def

        self.records.append(rec)
        if rec.round_ended:
            self.round_records.append({
                'round': self.current_round, 'start_rnd': self.round_starts_at,
                'end_rnd': self.rnd, 'winner': rec.round_winner or '—',
                'games_count': self.rnd - self.round_starts_at + 1,
            })
            self.current_round += 1
            self.round_starts_at = self.rnd + 1
        if self.total_rounds and self.current_round > self.total_rounds:
            self.game_over_flag = True

        settle_parts = [f"🎯 结算: 得分 {rec.attacker_score}",
                        f"庄家方 +{rec.final_up_def} | 闲家 +{rec.final_up_att}"]
        if rec.bonus_up > 0:
            settle_parts.append(f"扣底奖励 +{rec.bonus_up}")
        if rec.result_title:
            settle_parts.append(rec.result_title)
        rec.events.append({
            'type': 'settle', 'attacker_score': rec.attacker_score,
            'final_up_def': rec.final_up_def, 'final_up_att': rec.final_up_att,
            'bonus_up': rec.bonus_up, 'result_title': rec.result_title,
            'round_ended': rec.round_ended, 'round_winner': rec.round_winner,
            'text': ' | '.join(settle_parts),
        })
        self._set_status(f"结算完成 | 庄家方={self.defender_level} 抓分方={self.attacker_level}")

    def _reset_round_state(self):
        self.team_a_cumulative_steps = 0
        self.team_b_cumulative_steps = 0
        self.defending_team = None
        self.team_a_level = '7'
        self.team_b_level = '7'
        self.defender_level = '7'
        self.attacker_level = '7'
        self._next_defender_level = '7'
        self._next_attacker_level = '7'

    # ==================== 步进状态机 ====================

    def init_game(self):
        self.running = True
        self.step_mode = True
        self.game_over_flag = False
        self.winner = None
        self.limit_reached = False

        self.dealer_pid = random.randint(0, 3)
        self.defender_level = '7'
        self.attacker_level = '7'
        self._next_defender_level = '7'
        self._next_attacker_level = '7'
        self.team_a_level = '7'
        self.team_b_level = '7'
        self.rnd = 0
        self.current_round = 1
        self.round_starts_at = 1
        self.records = []
        self.round_records = []
        self.defending_team = None
        self.team_a_cumulative_steps = 0
        self.team_b_cumulative_steps = 0

        self._step_next_round()
        self._set_status("步进模式 | 点击「下一步」推进")

        # 回放时间线初始化: 第 1 局起点即快照 0
        self._timeline = [self._get_snapshot()]
        self._view = 0
        self._live_steps = 0
        self._round_start_step = {1: 0}
        return self._serve()

    def _step_next_round(self):
        if self.game_over_flag:
            return

        self.defender_level = self._next_defender_level
        self.attacker_level = self._next_attacker_level

        self.rnd += 1
        dt = [self.dealer_pid, (self.dealer_pid + 2) % 4]
        at = [(self.dealer_pid + 1) % 4, (self.dealer_pid + 3) % 4]
        self.dt = dt
        self.at = at
        self.rec = RoundRecord(self.rnd, self.dealer_pid, self.defender_level, self.attacker_level)
        self.rec.dealer_team = dt
        self.rec.attacker_team = at
        self.rec.level = self.defender_level

        # 结构化事件流: 供 文字记录 面板按时间线展示
        self.rec.events = []
        self.rec.events.append({
            'type': 'round', 'rnd': self.rnd, 'dealer_pid': self.dealer_pid,
            'def': self.defender_level, 'att': self.attacker_level,
            'dt': list(dt), 'at': list(at),
            'text': f"=== 第 {self.rnd} 局 | 庄=玩家{self.dealer_pid + 1} 打 {self.defender_level} "
                    f"| 庄:玩{dt[0] + 1}、玩{dt[1] + 1} | 抓:玩{at[0] + 1}、玩{at[1] + 1} ===",
        })

        self._set_status(f"第 {self.rnd} 局 | 庄家方={self.defender_level} 抓分方={self.attacker_level}")
        self.bots = {}
        self.trick_idx = 0
        self.current_trick = None
        self._deal()
        self.engine_state = 'trump'

    def step(self):
        """推进一步 — 1:1 复刻 gui._do_one_step。

        回放态(view<live_steps)前进只移动游标、不复算引擎；
        实时前沿才真正执行一步并归档快照。"""
        if self._view < self._live_steps:          # 回放中前进: 仅移游标
            self._view += 1
            return self._serve()
        if self.game_over_flag:                    # 已结束: 不再增长时间线
            self._finish_game()
            return self._serve()

        # 达 1000 局上限且已结算: 冻结, 不开新局 (仅回放/导出/重置可用)
        if (self.engine_state == 'settled' and not self.game_over_flag
                and len(self.records) >= MAX_RECORDS):
            if not self.limit_reached:
                self.limit_reached = True
                self._set_status(f'⚠️ 已达 {MAX_RECORDS} 局上限 | 可回放/导出，开始新对局前请先「重置对局」')
            self._timeline[self._view] = self._get_snapshot()   # 刷新当前快照(带 limit 标记)
            return self._serve()

        prev_rnd = self.rnd
        if self.engine_state == 'trump':
            self._do_trump_stage()
        elif self.engine_state == 'bury':
            self._do_bury_stage()
        elif self.engine_state == 'pick':
            self._do_pick_stage()
        elif self.engine_state == 'playing':
            self._play_next_trick()
        elif self.engine_state == 'settled':
            self._set_status(f"结算完成 | 庄家方={self.defender_level} 抓分方={self.attacker_level}")
            if not self.game_over_flag:
                self._step_next_round()

        if self.game_over_flag:
            self._finish_game()

        # 归档一步（结算步会连同本局结算帧; 跨局时下一步即新局起点）
        self._live_steps += 1
        self._timeline.append(self._get_snapshot())
        self._view = self._live_steps
        if self.rnd != prev_rnd:
            self._round_start_step[self.rnd] = self._live_steps
        return self._serve()

    # ==================== 回放（参考三副牌 v1.2）====================

    def _serve(self):
        """当前视图快照 + 回放游标字段。快照本身只读，不回放时也不改动。"""
        snap = dict(self._timeline[self._view])
        snap['view'] = self._view
        snap['live_steps'] = self._live_steps
        snap['replay'] = self._view < self._live_steps   # 是否回放态
        snap['can_prev'] = self._view > 0
        return snap

    def prev_step(self):
        """上一步: 仅移游标"""
        if self._view > 0:
            self._view -= 1
        return self._serve()

    def replay_round(self, rnd):
        """跳到指定局的起始快照"""
        start = self._round_start_step.get(rnd)
        if start is None:
            return None
        self._view = start
        return self._serve()

    def live(self):
        """退出回放: 回到实时前沿"""
        self._view = self._live_steps
        return self._serve()

    def _game_rows(self):
        """对局记录: 已完结各局的一行摘要（不含当前未完结局）"""
        rows = []
        for r in self.records:
            rows.append({
                'rnd': r.rnd,
                'level': r.level,
                'dealer_pid': r.dealer_pid,
                'trump_suit': r.trump_suit,
                'trump_method': r.trump_method,
                'attacker_score': r.attacker_score,
                'final_up_def': r.final_up_def,
                'final_up_att': r.final_up_att,
                'result_title': r.result_title or '',
            })
        return rows

    def _finish_game(self):
        self.running = False
        self._reveal_count = None
        self._pending_trick = None
        self._set_status(f"🏆 游戏结束 | 胜方: {self.winner or '—'}")

    def _set_status(self, text):
        self._last_status = text

    # ==================== 序列化 ====================

    def _get_snapshot(self):
        rec = self.rec
        trump_suit = rec.trump_suit if rec else None
        level = rec.level if rec else self.defender_level

        # 手牌排序（同 gui.py: 按 cp 排序，降序）
        hands_data = {}
        for pid in range(4):
            if self.engine_state in ('playing', 'settled') and self.bots and pid in self.bots:
                source = self.bots[pid].hand
            elif self.hands and pid < len(self.hands):
                source = self.hands[pid]
            elif self.bots and pid in self.bots:
                source = self.bots[pid].hand
            else:
                source = []

            if trump_suit:
                sorted_hand = sorted(source, key=lambda c: cp(c, level, trump_suit), reverse=True)
            else:
                sorted_hand = sorted(source, key=lambda c: RANK_ORDER.get(c.rank, 0), reverse=True)
            hands_data[str(pid)] = self._cards_to_dicts(sorted_hand)

        data = {
            'state': self.engine_state,
            'round': self.rnd,
            'current_round': self.current_round,
            'game_over': self.game_over_flag,
            'seed': self.seed,
            'dealer_pid': self.dealer_pid,
            'defender_level': self.defender_level,
            'attacker_level': self.attacker_level,
            'team_a_level': self.team_a_level,
            'team_b_level': self.team_b_level,
            'next_defender_level': self._next_defender_level,
            'next_attacker_level': self._next_attacker_level,
            'defending_team': self.defending_team,
            'dt': self.dt,
            'at': self.at,
            'hands': hands_data,
            'bottom': self._cards_to_dicts(self.bottom),
            'status': self._last_status,
            'reveal_count': self._reveal_count,
            'total_rounds': self.total_rounds,
            'records_count': len(self.records),
            'limit_reached': self.limit_reached,
            'round_records': self.round_records,
        }

        if rec:
            data['round_record'] = {
                'rnd': rec.rnd,
                'level': rec.level,
                'initial_bottom': self._cards_to_dicts(rec.initial_bottom),
                'trump_method': rec.trump_method,
                'trump_suit': rec.trump_suit,
                'trump_suit_cn': SUIT_CN.get(rec.trump_suit, '') if rec.trump_suit else '',
                'bright_pid': rec.bright_pid,
                'bright_card': self._card_to_dict(rec.bright_card) if rec.bright_card else None,
                'concealed_pid': rec.concealed_pid,
                'concealed_card': self._card_to_dict(rec.concealed_card) if rec.concealed_card else None,
                'buried_cards': self._cards_to_dicts(rec.buried_cards),
                'bottom_after_bury': self._cards_to_dicts(rec.bottom_after_bury),
                'picked_from_bottom': self._cards_to_dicts(rec.picked_from_bottom),
                'discarded_to_bottom': self._cards_to_dicts(rec.discarded_to_bottom),
                'bottom_after_pick': self._cards_to_dicts(rec.bottom_after_pick),
                'tricks': [
                    {
                        'num': t['num'],
                        'leader': t['leader'],
                        'played': [
                            {
                                'pid': pid,
                                'cards': self._cards_to_dicts(cl) if isinstance(cl, list) else [
                                    self._card_to_dict(cl)]
                            }
                            for pid, cl in t['played']
                        ],
                        'winner': t.get('winner'),
                        'winner_side': t.get('winner_side'),
                        'score': t.get('score', 0),
                        'pattern': t.get('pattern', 'single'),
                    }
                    for t in rec.tricks
                ],
                'attacker_score': rec.attacker_score,
                'base_up_att': rec.base_up_att,
                'final_up_def': rec.final_up_def,
                'final_up_att': rec.final_up_att,
                'bonus_up': rec.bonus_up,
                'last_trick_winner_pid': rec.last_trick_winner_pid,
                'last_trick_winner_side': rec.last_trick_winner_side,
                'last_trick_card': self._card_to_dict(rec.last_trick_card) if rec.last_trick_card else None,
                'result_title': rec.result_title,
                'round_ended': getattr(rec, 'round_ended', False),
                'round_winner': getattr(rec, 'round_winner', None),
            }

        if self.current_trick:
            data['current_trick'] = {
                'num': self.current_trick['num'],
                'leader': self.current_trick['leader'],
                'played': [
                    {
                        'pid': pid,
                        'cards': self._cards_to_dicts(cl) if isinstance(cl, list) else [
                            self._card_to_dict(cl)]
                    }
                    for pid, cl in self.current_trick['played']
                ],
                'winner': self.current_trick.get('winner'),
                'score': self.current_trick.get('score', 0),
                'pattern': self.current_trick.get('pattern', 'single'),
            }

        if self.game_over_flag:
            data['winner'] = self.winner

        return data


# ==================== API 路由 ====================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/new', methods=['POST'])
def api_new():
    data = request.json or {}
    seed = data.get('seed')
    total_rounds = data.get('total_rounds')
    deal_requirements = data.get('deal_requirements') or {}

    # 解析 deal_requirements (e.g. {"hong": [1,2]})
    parsed_reqs = {}
    for key, val in deal_requirements.items():
        if val and key in ('hong', 'zha', '510k'):
            if isinstance(val, list) and len(val) == 2:
                parsed_reqs[key] = (val[0], val[1])
            elif isinstance(val, (int, str)):
                n = int(val)
                parsed_reqs[key] = (n, n)

    sid = f"game_{int(time.time() * 1000)}_{len(sessions)}"
    sess = WebSession(seed=seed, total_rounds=total_rounds, deal_requirements=parsed_reqs)
    sessions[sid] = sess
    snapshot = sess.init_game()
    return jsonify({'session_id': sid, **snapshot})


@app.route('/api/step', methods=['POST'])
def api_step():
    sid = request.json.get('session_id')
    _cleanup_sessions()
    sess = sessions.get(sid)
    if not sess:
        return jsonify({'error': 'session not found'}), 404
    sess._last_access = time.time()
    snapshot = sess.step()
    return jsonify(snapshot)


@app.route('/api/status', methods=['GET'])
def api_status():
    sid = request.args.get('session_id')
    _cleanup_sessions()
    sess = sessions.get(sid)
    if not sess:
        return jsonify({'error': 'session not found'}), 404
    sess._last_access = time.time()
    return jsonify(sess._serve())


@app.route('/api/prev', methods=['POST'])
def api_prev():
    sid = request.json.get('session_id')
    _cleanup_sessions()
    sess = sessions.get(sid)
    if not sess:
        return jsonify({'error': 'session not found'}), 404
    sess._last_access = time.time()
    return jsonify(sess.prev_step())


@app.route('/api/replay', methods=['POST'])
def api_replay():
    sid = request.json.get('session_id')
    rnd = request.json.get('rnd')
    _cleanup_sessions()
    sess = sessions.get(sid)
    if not sess:
        return jsonify({'error': 'session not found'}), 404
    sess._last_access = time.time()
    snap = sess.replay_round(rnd)
    if snap is None:
        return jsonify({'error': 'round not found'}), 404
    return jsonify(snap)


@app.route('/api/live', methods=['POST'])
def api_live():
    sid = request.json.get('session_id')
    _cleanup_sessions()
    sess = sessions.get(sid)
    if not sess:
        return jsonify({'error': 'session not found'}), 404
    sess._last_access = time.time()
    return jsonify(sess.live())


@app.route('/api/games', methods=['GET'])
def api_games():
    sid = request.args.get('session_id')
    _cleanup_sessions()
    sess = sessions.get(sid)
    if not sess:
        return jsonify({'error': 'session not found'}), 404
    sess._last_access = time.time()
    return jsonify({'games': sess._game_rows()})


@app.route('/api/logs', methods=['GET'])
def api_logs():
    sid = request.args.get('session_id')
    rnd = request.args.get('rnd', type=int)
    _cleanup_sessions()
    sess = sessions.get(sid)
    if not sess:
        return jsonify({'error': 'session not found'}), 404
    sess._last_access = time.time()
    rec = None
    if rnd is not None:
        for r in sess.records:
            if r.rnd == rnd:
                rec = r
                break
        if rec is None and sess.rec and sess.rec.rnd == rnd:
            rec = sess.rec
    events = getattr(rec, 'events', None) if rec else None
    return jsonify({'rnd': rnd, 'events': events or []})


@app.route('/api/reset', methods=['POST'])
def api_reset():
    sid = request.json.get('session_id')
    if sid in sessions:
        del sessions[sid]
    return jsonify({'status': 'ok'})


@app.route('/api/export', methods=['POST'])
def api_export():
    sid = request.json.get('session_id')
    _cleanup_sessions()
    sess = sessions.get(sid)
    if not sess:
        return jsonify({'error': 'session not found'}), 404
    sess._last_access = time.time()

    # 使用 gui.py 的 save_excel 逻辑
    class _FakeGame:
        pass

    g = _FakeGame()
    g.winner = sess.winner
    g.round_records = sess.round_records
    g.records = sess.records

    buf = io.BytesIO()
    save_excel(sess.records, g, buf)  # save_excel 接受文件路径或文件对象
    buf.seek(0)

    fname = f"升级_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name=fname)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--no-debug', action='store_true')
    parser.add_argument('--port', type=int, default=5000)
    args = parser.parse_args()
    print("== One-Deck Shengji Web ==")
    print(f"  -> http://localhost:{args.port}")
    app.run(host='0.0.0.0', port=args.port, debug=not args.no_debug)
