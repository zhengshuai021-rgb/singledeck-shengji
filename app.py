#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一副牌升级 · Web 版 — Flask 后端（包装 game.py 引擎）"""

import sys
import os
import json
import random
from flask import Flask, render_template, jsonify, request, send_file

sys.path.insert(0, os.path.dirname(__file__))

# --- 从 game.py 导入 ---
from game import (
    create_deck, Card, Bot, RoundRecord,
    SUITS, SUIT_CN, SCORE_RANKS, SCORE_VALUES, RANK_ORDER,
    cp, is_main, cards_str, LEVEL_CYCLE,
    level_up, level_idx,
    find_hongs, find_510k, find_zhas,
    count_hand_patterns, check_deal_requirements,
    compare_trick_patterns, max_card_in_trick,
    save_excel, Game
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

class WebSession:
    """包装 Game 引擎的 Web 会话"""

    def __init__(self, seed=None, total_rounds=None):
        self.seed = seed if seed is not None else random.randint(1, 999999)
        random.seed(self.seed)

        self.game = Game(total_rounds=total_rounds)
        self.game.rnd = 0  # 手动控制

        self.step_index = 0
        self.engine_state = 'idle'

        # 当前局数据
        self.rec = None
        self.current_trick = None
        self.hands_snapshot = {}
        self.bottom_snapshot = []
        self.trick_phase = 'idle'  # idle / playing / done

    def _card_to_dict(self, card):
        if card is None: return None
        return {'suit': card.suit, 'rank': card.rank}

    def _cards_to_dicts(self, cards):
        if cards is None: return []
        return [self._card_to_dict(c) for c in cards]

    def _hand_to_dicts(self, hand_pid, hands):
        cards = hands[hand_pid] if hands and hand_pid < len(hands) else []
        return sorted([self._card_to_dict(c) for c in cards],
                     key=lambda c: (c.get('suit', ''), c.get('rank', '')))

    def start_game(self):
        """开始新局 — 只发牌，定主阶段留给 step 处理"""
        g = self.game
        g.rnd += 1

        dt = [g.dealer_pid, (g.dealer_pid + 2) % 4]
        at = [(g.dealer_pid + 1) % 4, (g.dealer_pid + 3) % 4]

        self.rec = RoundRecord(g.rnd, g.dealer_pid, g.defender_level, g.attacker_level)
        self.rec.dealer_team = dt
        self.rec.attacker_team = at
        self.rec.level = g.defender_level

        # 发牌
        for attempt in range(100000):
            deck = create_deck()
            random.shuffle(deck)
            hands = [[] for _ in range(4)]
            bottom = []
            for i, card in enumerate(deck):
                (hands[i % 4] if i < 48 else bottom).append(card)
            if not g.deal_requirements or check_deal_requirements(hands, g.deal_requirements):
                self.rec.initial_hands = {p: list(h) for p, h in enumerate(hands)}
                self.rec.initial_bottom = list(bottom)
                break

        self.hands_snapshot = {p: list(h) for p, h in enumerate(self.rec.initial_hands.values())}
        self.bottom_snapshot = list(self.rec.initial_bottom)

        # 进入定主阶段（由 step 逐步执行）
        self.engine_state = 'trump'
        self.trick_phase = 'idle'
        return self._get_snapshot()

    def _determine_trump(self, dt, at):
        rec = self.rec
        hands = self.hands_snapshot
        lvl = rec.level
        trump_decided = False

        # 闷牌
        for pid in range(4):
            lc = [c for c in hands[pid] if c.rank == lvl and c.suit in SUITS]
            if lc and random.random() < 0.25:
                card = random.choice(lc)
                rec.concealed_pid, rec.concealed_card = pid, card
                rec.trump_method = 'concealed'
                trump_decided = True
                break

        # 亮牌
        if not trump_decided:
            for pid in dt:
                lc = [c for c in hands[pid] if c.rank == lvl and c.suit in SUITS]
                if lc and random.random() < 0.5:
                    card = random.choice(lc)
                    rec.bright_pid, rec.bright_card = pid, card
                    rec.trump_suit, rec.trump_method = card.suit, 'bright'
                    trump_decided = True
                    break

        if not trump_decided:
            for pid in at:
                lc = [c for c in hands[pid] if c.rank == lvl and c.suit in SUITS]
                if lc and random.random() < 0.5:
                    card = random.choice(lc)
                    rec.concealed_pid, rec.concealed_card = pid, card
                    rec.trump_method = 'concealed'
                    trump_decided = True
                    break

        if not trump_decided:
            fc = next((c for c in rec.initial_bottom if c.suit in SUITS), None)
            rec.trump_suit = fc.suit if fc else random.choice(SUITS)
            rec.trump_method = 'bottom_card'

        # 闷牌变亮牌
        if (rec.trump_method == 'concealed'
                and rec.concealed_pid is not None
                and rec.concealed_pid in rec.dealer_team):
            rec.bright_pid = rec.concealed_pid
            rec.bright_card = rec.concealed_card
            rec.trump_suit = rec.concealed_card.suit
            rec.trump_method = 'bright'
            rec.concealed_pid = None
            rec.concealed_card = None

        # 进入埋底阶段
        self.engine_state = 'bury'
        self.trick_phase = 'idle'
        # _bury 由 step() 下次调用执行

    def _bury(self, dt=None, at=None):
        rec = self.rec
        hands = self.hands_snapshot
        pid = rec.dealer_pid
        bottom = list(rec.initial_bottom)
        bot = Bot(pid, list(hands[pid]), 'dealer', rec.level, rec.trump_suit or '')
        n = random.randint(0, 6)
        buried = bot.select_for_bottom(n)
        temp_bottom = bottom + buried

        score = sum(SCORE_VALUES.get(c.rank, 0) for c in temp_bottom)
        for _ in range(10):
            if score <= 35: break
            sc = [c for c in buried if c.rank in SCORE_RANKS]
            if not sc: break
            buried.remove(sc[0]); bot.hand.append(sc[0])
            temp_bottom = bottom + buried
            score = sum(SCORE_VALUES.get(c.rank, 0) for c in temp_bottom)

        take_back = temp_bottom[:len(buried)]
        new_bottom = temp_bottom[len(buried):]
        bot.hand.extend(take_back)
        hands[pid] = list(bot.hand)

        rec.buried_cards = list(buried)
        rec.bottom_after_bury = list(new_bottom)
        self.bottom_snapshot = list(new_bottom)

        # 判断下一步：有闷牌 → pick，否则 → playing
        if rec.concealed_pid is not None:
            self.engine_state = 'pick'
            self.trick_phase = 'idle'
        else:
            self._finalize_prep(dt, at)

    def _pick_main(self, dt=None, at=None):
        """捡主阶段 — 闷牌玩家翻开底牌拣出主牌"""
        rec = self.rec
        hands = self.hands_snapshot
        pid = rec.concealed_pid
        ts = rec.concealed_card.suit
        rec.trump_suit = ts
        bottom = list(rec.bottom_after_bury)
        bot = Bot(pid, list(hands[pid]), 'attacker', rec.level, ts)
        picked = [c for c in bottom if is_main(c, rec.level, ts)]
        if picked:
            rec.picked_from_bottom = list(picked)
            bottom_rem = [c for c in bottom if c not in picked]
            bot.hand.extend(picked)
            discarded = bot.select_for_bottom(len(picked))
            new_bottom = bottom_rem + discarded
            new_bs = sum(SCORE_VALUES.get(c.rank, 0) for c in new_bottom)
            if new_bs <= 35:
                hands[pid] = list(bot.hand)
                rec.discarded_to_bottom = list(discarded)
                rec.bottom_after_pick = list(new_bottom)
                self.bottom_snapshot = list(new_bottom)

        # 埋底完成后进入 playing
        self._finalize_prep()

    def _finalize_prep(self, dt=None, at=None):
        rec = self.rec
        hands = self.hands_snapshot
        # Get teams from rec if not provided
        if dt is None: dt = rec.dealer_team
        if at is None: at = rec.attacker_team
        self.bots = {}
        for pid in range(4):
            side = 'dealer' if pid in dt else 'attacker'
            # 直接传递 hands 的引用，让 Bot 修改同步
            self.bots[pid] = Bot(pid, hands[pid], side, rec.level, rec.trump_suit)
        self.trick_leader = self.game.dealer_pid
        self.trick_idx = 0
        self.current_trick = None
        rec.tricks = []
        self.engine_state = 'playing'
        self.trick_phase = 'idle'

    def step(self):
        """推进一步（逐步状态机：idle→trump→bury→pick→playing→settled）"""
        g = self.game
        rec = self.rec
        dt = [g.dealer_pid, (g.dealer_pid + 2) % 4]
        at = [(g.dealer_pid + 1) % 4, (g.dealer_pid + 3) % 4]

        if rec is None or g.game_over:
            return self._get_snapshot()

        if self.engine_state == 'idle':
            # 还没开始，先 start（发牌）
            return self.start_game()

        elif self.engine_state == 'trump':
            # 定主：判断亮/闷牌
            self._determine_trump(dt, at)
            # 如果不需要埋底（理论上不会发生），直接跳到 playing
            if self.rec.trump_method == 'bottom_card':
                self._finalize_prep(dt, at)
            # 否则进入埋底阶段

        elif self.engine_state == 'bury':
            # 埋底：庄家埋底牌
            self._bury(dt, at)
            # _bury 内部可能调用 _pick_main 或 _finalize_prep
            # 根据状态判断下一步
            if self.engine_state == 'pick':
                pass  # _bury 已设置 pick 状态
            elif self.engine_state == 'playing':
                pass  # _bury 直接进入 playing
            return self._get_snapshot()

        elif self.engine_state == 'pick':
            # 捡主：闷牌玩家捡主
            self._pick_main(dt, at)
            # _pick_main 内部调用 _finalize_prep 进入 playing

        elif self.engine_state == 'playing':
            # 出一圈牌
            self._play_one_trick()

        elif self.engine_state == 'settled':
            # 结算完成，开新局
            self.start_game()

        return self._get_snapshot()

    def _play_one_trick(self):
        """完整出一圈牌"""
        g = self.game
        rec = self.rec
        dt = rec.dealer_team
        at = rec.attacker_team
        bots = self.bots

        if self.trick_idx >= 12:
            self._settle_and_continue()
            return

        if any(len(bots[p].hand) == 0 for p in range(4)):
            self._settle_and_continue()
            return

        t = self.trick_idx + 1
        trick = {'num': t, 'leader': self.trick_leader, 'played': [], 'winner': None,
                 'winner_side': None, 'score': 0, 'score_cards': [], 'pattern': 'single'}
        lead_suit = None
        played_so_far = []

        for pos in range(4):
            pid = (self.trick_leader + pos) % 4
            if not bots[pid].hand:
                trick['played'].append((pid, []))
                played_so_far.append((pid, []))
                continue
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

        # 确定赢家
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
        self.current_trick = trick
        self.trick_leader = best_pid

        # 更新手牌快照
        for pid in range(4):
            self.hands_snapshot[pid] = list(bots[pid].hand)

        # 检查是否出完
        if any(len(bots[p].hand) == 0 for p in range(4)):
            self._settle_and_continue()

    def _settle_and_continue(self):
        """结算本局"""
        g = self.game
        rec = self.rec

        self.engine_state = 'settled'
        self.current_trick = None

        sc = sum(tr['score'] for tr in rec.tricks)
        rec.attacker_score = sc
        is_bottom = False
        if rec.tricks:
            lt = rec.tricks[-1]
            rec.last_trick_winner_pid = lt['winner']
            rec.last_trick_winner_side = lt['winner_side']
            is_bottom = lt['winner_side'] == 'attacker'
            for pid, cl in lt['played']:
                if pid == lt['winner']:
                    rec.last_trick_card = cl[-1] if cl else None
                    break

        # 升级计算
        if sc == 0:
            rec.base_up_att = 0; rec.final_up_def = 3
        elif sc <= 35:
            rec.base_up_att = 0; rec.final_up_def = 1
        elif sc <= 39:
            rec.base_up_att = 0; rec.final_up_def = 0
        elif sc <= 45:
            rec.base_up_att = 0; rec.final_up_def = 0
        else:
            rec.base_up_att = min((sc - 50) // 10 + 1, 6)
            rec.final_up_def = 0

        bonus = 0
        if is_bottom:
            bonus = 4 if (rec.last_trick_card and rec.last_trick_card.rank == '大王') else 3
        rec.bonus_up = bonus

        if is_bottom and sc < 40:
            rec.final_up_def = 0; rec.base_up_att = 0; rec.bonus_up = 0

        rec.final_up_att = rec.base_up_att + bonus

        old_def = g.defender_level
        old_att = g.attacker_level

        if is_bottom and g.defending_team is None:
            g.defender_level = '7'
            g.attacker_level = '7'
        else:
            g.defender_level = level_up(g.defender_level, rec.final_up_def)
            g.attacker_level = level_up(g.attacker_level, rec.final_up_att)

        # 队伍等级
        if g.dealer_pid in (0, 2):
            g.team_a_cumulative_steps += rec.final_up_def
            g.team_b_cumulative_steps += rec.final_up_att
            g.team_a_level = level_up(g.team_a_level, rec.final_up_def)
            g.team_b_level = level_up(g.team_b_level, rec.final_up_att)
        else:
            g.team_b_cumulative_steps += rec.final_up_def
            g.team_a_cumulative_steps += rec.final_up_att
            g.team_b_level = level_up(g.team_b_level, rec.final_up_def)
            g.team_a_level = level_up(g.team_a_level, rec.final_up_att)

        # 结果标题
        if sc == 0:
            rec.result_title = '光头'
        elif sc <= 35:
            rec.result_title = '干受苦'
        elif sc <= 39:
            rec.result_title = '干受苦'
        elif sc <= 45:
            rec.result_title = '上台'
        else:
            rec.result_title = f"升{rec.base_up_att}级"

        if is_bottom and sc < 40:
            rec.result_title = '干扣底'

        # 守庄局锁定等级
        if g.defending_team:
            g.team_a_level = '7'
            g.team_b_level = '7'
            g.defender_level = '7'
            g.attacker_level = '7'

        # 过7 检查（简化版）
        self._check_over7(rec)

        if not rec.round_ended:
            # 庄权交换
            if rec.final_up_att > 0:
                new_dealer = rec.attacker_team[0]
                if new_dealer != g.dealer_pid:
                    g.dealer_pid = new_dealer
                    g.defender_level, g.attacker_level = g.attacker_level, g.defender_level

        g.records.append(rec)

        if g.total_rounds and g.current_round > g.total_rounds:
            g.game_over = True

        if rec.round_ended:
            g.round_records.append({
                'round': g.current_round,
                'start_rnd': rec.rnd if hasattr(rec, 'rnd') else g.rnd,
                'end_rnd': g.rnd,
                'winner': rec.round_winner or '—',
                'games_count': g.rnd - g.round_starts_at + 1,
            })
            g.current_round += 1
            g.round_starts_at = g.rnd + 1

    def _check_over7(self, rec):
        g = self.game

        def _has_over7(lvl):
            return level_idx(lvl) > 0

        if g.defending_team:
            is_A = g.defending_team == 'A'
            def_lvl = g.team_a_level if is_A else g.team_b_level
            opp_lvl = g.team_b_level if is_A else g.team_a_level
            dname = f'队伍{g.defending_team}'
            oname = '队伍B' if is_A else '队伍A'

            if rec.attacker_score <= 35:
                rec.result_title = f'{dname}守庄成功🏆'
                rec.round_ended = True
                rec.round_winner = dname
                g.game_over = True
                g.winner = f'{dname}（守庄方）'
                return
            if _has_over7(def_lvl):
                rec.result_title = f'{dname}过7🏆'
                rec.round_ended = True
                rec.round_winner = dname
                g.game_over = True
                g.winner = f'{dname}（守庄方）'
                return
            if _has_over7(opp_lvl):
                rec.result_title = f'{oname}过7🏆'
                rec.round_ended = True
                rec.round_winner = oname
                g.game_over = True
                g.winner = f'{oname}（庄家方）'
                return
            return

        dealer_is_a = g.dealer_pid in (0, 2)
        dealer_lvl = g.team_a_level if dealer_is_a else g.team_b_level
        attacker_lvl = g.team_b_level if dealer_is_a else g.team_a_level
        dlabel = '队伍A' if dealer_is_a else '队伍B'
        alabel = '队伍B' if dealer_is_a else '队伍A'

        if _has_over7(dealer_lvl):
            rec.result_title = f'{dlabel}过7🏆'
            rec.round_ended = True
            rec.round_winner = dlabel
            g.game_over = True
            g.winner = f'{dlabel}（庄家方）'
            return

        if _has_over7(attacker_lvl):
            new_dealer = rec.attacker_team[0]
            if new_dealer != g.dealer_pid:
                g.dealer_pid = new_dealer
                g.defender_level = '7'
                g.attacker_level = '7'
            rec.result_title = f'{alabel}过7→守庄🏰'
            rec.round_ended = True
            rec.round_winner = f'{alabel}（进入守庄）'
            g.defending_team = 'B' if dealer_is_a else 'A'
            return

        if rec.final_up_att > 0:
            new_dealer = rec.attacker_team[0]
            if new_dealer != g.dealer_pid:
                g.dealer_pid = new_dealer
                g.defender_level, g.attacker_level = g.attacker_level, g.defender_level

    def _get_snapshot(self):
        g = self.game
        rec = self.rec
        data = {
            'state': self.engine_state,
            'round': g.rnd,
            'current_round': g.current_round,
            'game_over': g.game_over,
            'seed': self.seed,
            'dealer_pid': g.dealer_pid,
            'defender_level': g.defender_level,
            'attacker_level': g.attacker_level,
            'team_a_level': g.team_a_level,
            'team_b_level': g.team_b_level,
            'defending_team': g.defending_team,
            'dt': rec.dealer_team if rec else [],
            'at': rec.attacker_team if rec else [],
            'hands': {str(i): self._hand_to_dicts(i, self.hands_snapshot) for i in range(4)},
            'bottom': self._cards_to_dicts(self.bottom_snapshot),
            'total_rounds': g.total_rounds,
            'records_count': len(g.records),
            'round_records': g.round_records,
        }

        if rec:
            data['round_record'] = {
                'rnd': rec.rnd,
                'level': rec.level,
                'trump_method': rec.trump_method,
                'trump_suit': rec.trump_suit,
                'trump_suit_cn': SUIT_CN.get(rec.trump_suit, ''),
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
                                'cards': self._cards_to_dicts(cl) if isinstance(cl, list) else [self._card_to_dict(cl)]
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
                'final_up_def': rec.final_up_def,
                'final_up_att': rec.final_up_att,
                'bonus_up': rec.bonus_up,
                'result_title': rec.result_title,
                'round_ended': rec.round_ended,
                'round_winner': rec.round_winner,
            }

        if self.current_trick:
            data['current_trick'] = {
                'num': self.current_trick['num'],
                'leader': self.current_trick['leader'],
                'played': [
                    {
                        'pid': pid,
                        'cards': self._cards_to_dicts(cl) if isinstance(cl, list) else [self._card_to_dict(cl)]
                    }
                    for pid, cl in self.current_trick['played']
                ],
                'winner': self.current_trick.get('winner'),
                'score': self.current_trick.get('score', 0),
                'pattern': self.current_trick.get('pattern', 'single'),
            }

        if g.game_over:
            data['winner'] = g.winner

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
    sid = f"game_{len(sessions)}"
    sess = WebSession(seed=seed, total_rounds=total_rounds)
    sessions[sid] = sess
    snapshot = sess.start_game()
    return jsonify({'session_id': sid, **snapshot})

@app.route('/api/step', methods=['POST'])
def api_step():
    sid = request.json.get('session_id')
    sess = sessions.get(sid)
    if not sess:
        return jsonify({'error': 'session not found'}), 404
    snapshot = sess.step()
    return jsonify(snapshot)

@app.route('/api/auto', methods=['POST'])
def api_auto():
    sid = request.json.get('session_id')
    steps = request.json.get('steps', 10)
    sess = sessions.get(sid)
    if not sess:
        return jsonify({'error': 'session not found'}), 404
    for _ in range(steps):
        snapshot = sess.step()
        if snapshot.get('game_over'):
            break
    return jsonify(snapshot)

@app.route('/api/status', methods=['GET'])
def api_status():
    sid = request.args.get('session_id')
    sess = sessions.get(sid)
    if not sess:
        return jsonify({'error': 'session not found'}), 404
    return jsonify(sess._get_snapshot())

@app.route('/api/reset', methods=['POST'])
def api_reset():
    sid = request.json.get('session_id')
    if sid in sessions:
        del sessions[sid]
    return jsonify({'status': 'ok'})


@app.route('/api/export', methods=['POST'])
def api_export():
    sid = request.json.get('session_id')
    sess = sessions.get(sid)
    if not sess:
        return jsonify({'error': 'session not found'}), 404
    g = sess.game
    # 空记录也允许导出（显示"游戏进行中"）
    # gui.py 逻辑：只要 records 有数据就可以导出，但空列表也可以生成空报告

    # 生成 Excel
    wb = _build_excel_workbook(g)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    fname = f"升级_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name=fname)


def _build_excel_workbook(g):
    """Build Excel workbook from Game state (同 gui.py export_excel)."""
    wb = Workbook()
    tf = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    tfont = Font(size=14, bold=True, color="FFFFFF")
    hf = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    hfont = Font(bold=True, color="FFFFFF")

    # Sheet1: 总览
    ws = wb.active
    ws.title = "游戏总览"
    ws.merge_cells('A1:P1')
    c = ws['A1']
    c.value = "一副牌升级游戏模拟（过7）"
    c.font = tfont; c.fill = tf; c.alignment = Alignment(horizontal='center')
    ws.merge_cells('A2:P2')
    total_games = len(g.records)
    total_r = len(g.round_records) if hasattr(g, 'round_records') else 0
    c = ws['A2']
    c.value = f"生成: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 共{total_r}轮{total_games}局 | 胜方: {g.winner or '未完成'}"
    c.font = Font(italic=True)

    hdrs = ['轮次','局数','庄家','庄方级(前)','抓方级(前)','本局级',
            '定主方式','亮牌/闷牌','主花色',
            '抓分','扣底','扣底牌',
            '抓方升级','庄方升级','庄方级(后)','抓方级(后)','结果']
    r = 4
    for col, h in enumerate(hdrs, 1):
        c = ws.cell(row=r, column=col, value=h)
        c.font = hfont; c.fill = hf; c.alignment = Alignment(horizontal='center')

    cur_def, cur_att = '7', '7'
    for i, rec in enumerate(g.records):
        r = 5 + i
        pre_def, pre_att = cur_def, cur_att

        if rec.trump_method == 'bright':
            tm, td = '亮牌', f"玩{rec.bright_pid+1}亮{rec.bright_card}"
        elif rec.trump_method == 'concealed':
            tm, td = '闷牌', f"玩{rec.concealed_pid+1}闷{rec.concealed_card}"
        else:
            tm, td = '底牌首张', '底牌首张定主'
        ts = SUIT_CN.get(rec.trump_suit, rec.trump_suit or '—')

        cur_def = level_up(cur_def, rec.final_up_def)
        cur_att = level_up(cur_att, rec.final_up_att)

        rnd_num = None
        if hasattr(g, 'round_records'):
            for rr in g.round_records:
                if rr['start_rnd'] <= rec.rnd <= rr['end_rnd']:
                    rnd_num = rr['round']
                    break

        bonus = rec.bonus_up if rec.bonus_up > 0 else 0

        ws.cell(row=r, column=1, value=rnd_num).alignment = Alignment(horizontal='center')
        ws.cell(row=r, column=2, value=rec.rnd).alignment = Alignment(horizontal='center')
        ws.cell(row=r, column=3, value=f"玩{rec.dealer_pid+1}").alignment = Alignment(horizontal='center')
        ws.cell(row=r, column=4, value=pre_def).alignment = Alignment(horizontal='center')
        ws.cell(row=r, column=5, value=pre_att).alignment = Alignment(horizontal='center')
        ws.cell(row=r, column=6, value=rec.level).alignment = Alignment(horizontal='center')
        ws.cell(row=r, column=7, value=tm).alignment = Alignment(horizontal='center')
        ws.cell(row=r, column=8, value=td).alignment = Alignment(horizontal='center')
        ws.cell(row=r, column=9, value=ts).alignment = Alignment(horizontal='center')
        ws.cell(row=r, column=10, value=rec.attacker_score).alignment = Alignment(horizontal='center')
        ws.cell(row=r, column=11, value=bonus).alignment = Alignment(horizontal='center')

        bottom_cards_str = ''
        if hasattr(rec, 'buried_cards') and rec.buried_cards:
            bottom_cards_str = ', '.join(f"{c.rank}{c.suit}" for c in rec.buried_cards)
        ws.cell(row=r, column=12, value=bottom_cards_str)

        ws.cell(row=r, column=13, value=rec.final_up_att).alignment = Alignment(horizontal='center')
        ws.cell(row=r, column=14, value=rec.final_up_def).alignment = Alignment(horizontal='center')
        ws.cell(row=r, column=15, value=cur_def).alignment = Alignment(horizontal='center')
        ws.cell(row=r, column=16, value=cur_att).alignment = Alignment(horizontal='center')
        ws.cell(row=r, column=17, value=rec.result_title).alignment = Alignment(horizontal='center')

    # Sheet2: 详细圈数
    if g.records:
        ws2 = wb.create_sheet("圈数详情")
        ws2.merge_cells('A1:J1')
        c2 = ws2['A1']
        c2.value = "每圈出牌记录"
        c2.font = tfont; c2.fill = tf; c2.alignment = Alignment(horizontal='center')

        hdrs2 = ['局数','圈数','先手','玩家1出牌','玩家2出牌','玩家3出牌','玩家4出牌',
                 '赢家','本圈得分','累计得分']
        r2 = 3
        for col, h in enumerate(hdrs2, 1):
            c = ws2.cell(row=r2, column=col, value=h)
            c.font = hfont; c.fill = hf; c.alignment = Alignment(horizontal='center')

        r2 = 4
        for rec in g.records:
            for t in rec.tricks:
                played_map = {}
                for pid, cl in t['played']:
                    played_map[pid] = cl if isinstance(cl, list) else [cl]

                cards_str = []
                for pid in range(4):
                    cl = played_map.get(pid, [])
                    cards_str.append(', '.join(f"{c.rank}{c.suit}" for c in cl))

                ws2.cell(row=r2, column=1, value=rec.rnd).alignment = Alignment(horizontal='center')
                ws2.cell(row=r2, column=2, value=t['num']).alignment = Alignment(horizontal='center')
                ws2.cell(row=r2, column=3, value=f"玩{t['leader']+1}").alignment = Alignment(horizontal='center')
                for pi, s in enumerate(cards_str):
                    ws2.cell(row=r2, column=4+pi, value=s)
                ws2.cell(row=r2, column=8, value=f"玩{t.get('winner')+1}" if t.get('winner') is not None else '').alignment = Alignment(horizontal='center')
                ws2.cell(row=r2, column=9, value=t.get('score', 0)).alignment = Alignment(horizontal='center')
                ws2.cell(row=r2, column=10, value=rec.attacker_score).alignment = Alignment(horizontal='center')
                r2 += 1

    return wb


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-debug', action='store_true')
    args = parser.parse_args()
    print("🎮 一副牌升级 · Web 版")
    print("  → http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=not args.no_debug)
