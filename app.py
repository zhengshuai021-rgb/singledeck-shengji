#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一副牌升级 · Web 版 — Flask 后端"""

import sys
import os
import json
import random
from datetime import datetime
from flask import Flask, render_template, jsonify, request

sys.path.insert(0, os.path.dirname(__file__))
from game import (
    create_deck, Card, Bot, RoundRecord,
    SUITS, SUIT_CN, SCORE_RANKS, SCORE_VALUES, RANK_ORDER,
    cp, is_main, cards_str, LEVEL_CYCLE,
    level_up, level_idx,
    find_hongs, find_510k, find_zhas,
    count_hand_patterns, check_deal_requirements,
    compare_trick_patterns, max_card_in_trick,
    save_excel
)

app = Flask(__name__, template_folder='web/templates', static_folder='web/static')

# ==================== 游戏会话管理 ====================

class WebGame:
    """一局 Web 游戏会话"""

    def __init__(self, seed=None, total_rounds=None):
        self.seed = seed if seed is not None else random.randint(1, 999999)
        random.seed(self.seed)

        self.total_rounds = total_rounds
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
        self.rnd = 0
        self.current_round = 1
        self.round_starts_at = 1
        self.records = []
        self.round_records = []
        self.game_over = False

        # 当前局数据
        self.hands = None
        self.bottom = None
        self.rec = None
        self.bots = {}
        self.dt = []
        self.at = []
        self.engine_state = 'idle'
        self.trick_leader = 0
        self.trick_idx = 0
        self.current_trick = None

    def start_game(self):
        """开始新一局"""
        if self.game_over:
            return None

        # 切换为下局等级
        self.defender_level = self._next_defender_level
        self.attacker_level = self._next_attacker_level

        self.rnd += 1
        self.dt = [self.dealer_pid, (self.dealer_pid + 2) % 4]
        self.at = [(self.dealer_pid + 1) % 4, (self.dealer_pid + 3) % 4]
        self.rec = RoundRecord(self.rnd, self.dealer_pid, self.defender_level, self.attacker_level)
        self.rec.dealer_team = self.dt
        self.rec.attacker_team = self.at
        self.rec.level = self.defender_level

        self._deal()
        self.engine_state = 'trump'
        return self._get_snapshot()

    def _deal(self):
        for attempt in range(100000):
            deck = create_deck()
            random.shuffle(deck)
            hands = [[] for _ in range(4)]
            bottom = []
            for i, card in enumerate(deck):
                (hands[i % 4] if i < 48 else bottom).append(card)
            self.hands = hands
            self.bottom = bottom
            self.rec.initial_hands = {p: list(h) for p, h in enumerate(hands)}
            self.rec.initial_bottom = list(bottom)
            return

    def step(self):
        """推进一步"""
        if self.game_over:
            return None

        if self.engine_state == 'trump':
            self._do_trump_stage()
        elif self.engine_state == 'bury':
            self._do_bury_stage()
        elif self.engine_state == 'pick':
            self._do_pick_stage()
        elif self.engine_state == 'playing':
            self._play_next_trick()
        elif self.engine_state == 'settled':
            self._settle_and_continue()

        return self._get_snapshot()

    def auto_play(self, steps=1):
        """自动推进 N 步"""
        for _ in range(steps):
            snap = self.step()
            if snap is None or snap.get('game_over'):
                break
        return self._get_snapshot()

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

        if rec.trump_method == 'concealed' and rec.concealed_pid is not None \
                and rec.concealed_pid in dt:
            rec.bright_pid = rec.concealed_pid
            rec.bright_card = rec.concealed_card
            rec.trump_suit = rec.concealed_card.suit
            rec.trump_method = 'bright'
            rec.concealed_pid = None
            rec.concealed_card = None

        self.engine_state = 'bury'

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
            if score <= 35: break
            sc = [c for c in buried if c.rank in SCORE_RANKS]
            if not sc: break
            buried.remove(sc[0]); bot.hand.append(sc[0])
            temp_bottom = bottom + buried
            score = sum(SCORE_VALUES.get(c.rank, 0) for c in temp_bottom)
        take_back = temp_bottom[:len(buried)]
        new_bottom = temp_bottom[len(buried):]
        bot.hand.extend(take_back)
        self.hands[pid] = bot.hand
        rec.buried_cards = list(buried)
        rec.bottom_after_bury = list(new_bottom)
        self.bottom = list(new_bottom)

        if rec.concealed_pid is not None:
            self.engine_state = 'pick'
        else:
            self._finalize_prep()

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
        self._finalize_prep()

    def _finalize_prep(self):
        rec = self.rec
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

    def _play_next_trick(self):
        if self.trick_idx >= 12:
            self._settle_and_continue()
            return

        dt, at = self.dt, self.at
        rec = self.rec
        bots = self.bots

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

        if any(len(bots[p].hand) == 0 for p in range(4)):
            self._settle_and_continue()

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

        is_bottom = rec.last_trick_winner_side == 'attacker'
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

        if rec.final_up_att > 0 or (sc <= 45 and sc >= 40):
            self._next_defender_level = new_att
            self._next_attacker_level = new_def
            self.dealer_pid = random.choice(self.at)
        else:
            self._next_defender_level = new_def
            self._next_attacker_level = new_att

        self._check_round_end(rec)
        if self.total_rounds and self.current_round > self.total_rounds:
            self.game_over = True
            self.winner = self._calc_winner()

        self.records.append(rec)

    def _check_round_end(self, rec):
        cur_dealer_is_a = self.dealer_pid in (0, 2)
        if cur_dealer_is_a:
            if self.team_a_level == '7' and self.defending_team != 'A':
                if self.team_b_level != '7' and self.team_b_level in LEVEL_CYCLE:
                    if level_idx(self.team_b_level) > level_idx('7'):
                        self.defending_team = 'B'
                        rec.round_ended = True
                        rec.round_winner = '队伍A'
            elif self.defending_team == 'A':
                if self.team_a_level == '7':
                    self.defending_team = None
                    rec.round_ended = True
                    rec.round_winner = '队伍B（攻下7）'
        else:
            if self.team_b_level == '7' and self.defending_team != 'B':
                if self.team_a_level != '7' and self.team_a_level in LEVEL_CYCLE:
                    if level_idx(self.team_a_level) > level_idx('7'):
                        self.defending_team = 'A'
                        rec.round_ended = True
                        rec.round_winner = '队伍B'
            elif self.defending_team == 'B':
                if self.team_b_level == '7':
                    self.defending_team = None
                    rec.round_ended = True
                    rec.round_winner = '队伍A（攻下7）'

        if not rec.round_ended:
            if self.defending_team is not None:
                if (self.defending_team == 'A' and self.team_a_level == '7' and
                        self.team_b_level == '7'):
                    rec.round_ended = True
                    rec.round_winner = '队伍B'
                elif (self.defending_team == 'B' and self.team_b_level == '7' and
                      self.team_a_level == '7'):
                    rec.round_ended = True
                    rec.round_winner = '队伍A'

        if rec.round_ended:
            self.round_records.append({
                'round': self.current_round,
                'start_rnd': self.round_starts_at,
                'end_rnd': self.rnd,
                'winner': rec.round_winner or '—',
                'games_count': self.rnd - self.round_starts_at + 1,
            })
            self.current_round += 1
            self.round_starts_at = self.rnd + 1
            if self.defending_team is None:
                self.defending_team = None

    def _calc_winner(self):
        if not self.round_records:
            return None
        last = self.round_records[-1]
        return last.get('winner')

    def _card_to_dict(self, card):
        return {'suit': card.suit, 'rank': card.rank}

    def _cards_to_dicts(self, cards):
        return [self._card_to_dict(c) for c in cards]

    def _hand_to_dicts(self, hand_pid):
        cards = self.hands[hand_pid] if self.hands and hand_pid < len(self.hands) else []
        return sorted([self._card_to_dict(c) for c in cards],
                     key=lambda c: (c.get('suit', ''), c.get('rank', '')))

    def _get_snapshot(self):
        rec = self.rec
        data = {
            'state': self.engine_state,
            'round': self.rnd,
            'current_round': self.current_round,
            'game_over': self.game_over,
            'seed': self.seed,
            'dealer_pid': self.dealer_pid,
            'defender_level': self.defender_level,
            'attacker_level': self.attacker_level,
            'team_a_level': self.team_a_level,
            'team_b_level': self.team_b_level,
            'defending_team': self.defending_team,
            'dt': self.dt,
            'at': self.at,
            'hands': {str(i): self._hand_to_dicts(i) for i in range(4)},
            'bottom': self._cards_to_dicts(self.bottom) if self.bottom else [],
            'total_rounds': self.total_rounds,
            'records_count': len(self.records),
            'round_records': self.round_records,
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
                'result': rec.result,
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

        if self.game_over:
            data['winner'] = self._calc_winner()

        return data


# ==================== 会话管理 ====================

sessions = {}

def get_session(sid):
    if sid not in sessions:
        sessions[sid] = WebGame()
    return sessions[sid]

def clear_session(sid):
    if sid in sessions:
        del sessions[sid]


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
    game = WebGame(seed=seed, total_rounds=total_rounds)
    sessions[sid] = game
    snapshot = game.start_game()
    return jsonify({'session_id': sid, **snapshot})

@app.route('/api/step', methods=['POST'])
def api_step():
    sid = request.json.get('session_id')
    game = get_session(sid)
    snapshot = game.step()
    return jsonify(snapshot)

@app.route('/api/auto', methods=['POST'])
def api_auto():
    sid = request.json.get('session_id')
    steps = request.json.get('steps', 10)
    game = get_session(sid)
    snapshot = game.auto_play(steps=steps)
    return jsonify(snapshot)

@app.route('/api/status', methods=['GET'])
def api_status():
    sid = request.args.get('session_id')
    game = get_session(sid)
    return jsonify(game._get_snapshot())

@app.route('/api/reset', methods=['POST'])
def api_reset():
    sid = request.json.get('session_id')
    clear_session(sid)
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    print("🎮 一副牌升级 · Web 版")
    print("  → http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)
