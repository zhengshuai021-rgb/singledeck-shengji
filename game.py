#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一副牌升级游戏模拟器
根据 PRD 实现完整游戏逻辑：发牌 → 定主 → 埋底 → 捡主 → 出牌 → 结算 → 过7

创建时间：2026-05-27
作者：Kami 🐱
"""

import random
import os
from datetime import datetime
from collections import defaultdict
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter

# ==================== 常量 ====================

SUITS = ['♠', '♥', '♣', '♦']
RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
SCORE_RANKS = {'5', '10', 'K'}
SCORE_VALUES = {'5': 5, '10': 10, 'K': 10}
RANK_ORDER = {rank: idx for idx, rank in enumerate(RANKS)}
SUIT_CN = {'♠': '黑桃', '♥': '红桃', '♣': '草花', '♦': '方块'}

# ==================== 牌类 ====================

class Card:
    def __init__(self, suit, rank):
        self.suit = suit
        self.rank = rank
    def __repr__(self):
        if self.rank in ('大王', '小王'): return self.rank
        return f"{self.suit}{self.rank}"
    def __eq__(self, other):
        return isinstance(other, Card) and self.suit == other.suit and self.rank == other.rank
    def __hash__(self):
        return hash((self.suit, self.rank))

def create_deck():
    deck = []
    for suit in SUITS:
        for rank in RANKS:
            deck.append(Card(suit, rank))
    deck.append(Card('王', '大王'))
    deck.append(Card('王', '小王'))
    return deck

def cards_str(cards):
    return ' '.join(str(c) for c in cards) if cards else '无'

# ==================== 牌力判定 ====================

def is_main(card, level, trump_suit):
    if card.rank in ('大王', '小王'): return True
    if card.rank == '3' and card.suit == '♥': return True
    if card.rank == '2': return True
    if card.rank == level: return True
    return False

def card_power(card, level, trump_suit):
    """(group, value): 5=大王 4=小王 3=级牌 2=常主 1=主牌 0=副牌"""
    if card.rank == '大王': return (5, 100)
    if card.rank == '小王': return (4, 100)
    if card.rank == level: return (3, RANK_ORDER[card.rank])
    if card.rank == '3' and card.suit == '♥': return (2, 100)
    if card.rank == '2': return (2, 90)
    if is_main(card, level, trump_suit): return (1, RANK_ORDER[card.rank])
    return (0, RANK_ORDER[card.rank])

def cp(card, level, trump_suit):
    """shortcut: combined power number"""
    g, v = card_power(card, level, trump_suit)
    return g * 1000 + v

def compare_cards(c1, c2, level, trump_suit, lead_suit):
    """1=c1大, -1=c2大"""
    c1_lead = c1.suit == lead_suit
    c2_lead = c2.suit == lead_suit
    c1_main = is_main(c1, level, trump_suit)
    c2_main = is_main(c2, level, trump_suit)

    if c1_lead and c2_lead:
        p1, p2 = card_power(c1, level, trump_suit), card_power(c2, level, trump_suit)
        if p1[0] != p2[0]: return 1 if p1[0] > p2[0] else -1
        return 1 if p1[1] > p2[1] else (-1 if p1[1] < p2[1] else 1)
    if c1_lead and not c2_lead:
        return -1 if c2_main else 1
    if not c1_lead and c2_lead:
        return 1 if c1_main else -1
    if c1_main and c2_main:
        p1, p2 = card_power(c1, level, trump_suit), card_power(c2, level, trump_suit)
        if p1[0] != p2[0]: return 1 if p1[0] > p2[0] else -1
        return 1 if p1[1] > p2[1] else (-1 if p1[1] < p2[1] else 1)
    if c1_main: return 1
    if c2_main: return -1
    return 1

def trick_current_best(cards, level, trump_suit, lead_suit):
    """返回当前赢家 (pid, card)"""
    best_pid, best_card = cards[0]
    for pid, card in cards[1:]:
        if compare_cards(card, best_card, level, trump_suit, lead_suit) == 1:
            best_pid, best_card = pid, card
    return best_pid, best_card

# ==================== 机器人 ====================

class Bot:
    def __init__(self, pid, hand, side, level, trump_suit):
        self.pid = pid
        self.hand = list(hand)
        self.side = side  # 'dealer' | 'attacker'
        self.level = level
        self.trump_suit = trump_suit

    def _non_score_offsuit(self):
        """非分牌且非主牌的牌"""
        return [c for c in self.hand if not is_main(c, self.level, self.trump_suit) and c.rank not in SCORE_RANKS]

    def _main_cards(self):
        """主牌（排除大王小王红桃3）"""
        return [c for c in self.hand if is_main(c, self.level, self.trump_suit)
                and c.rank not in ('大王', '小王')
                and not (c.rank == '3' and c.suit == '♥')]

    def _all_main(self):
        """所有主牌"""
        return [c for c in self.hand if is_main(c, self.level, self.trump_suit)]

    def lead(self):
        """首出：优先非分非主小牌"""
        safe = self._non_score_offsuit()
        if safe:
            safe.sort(key=lambda c: RANK_ORDER.get(c.rank, 0))
            card = safe[0]
        else:
            ns = [c for c in self.hand if c.rank not in SCORE_RANKS]
            card = min(ns if ns else self.hand, key=lambda c: RANK_ORDER.get(c.rank, 0))
        self.hand.remove(card)
        return card

    def follow(self, lead_suit, trick_so_far, is_last_trick=False):
        """跟牌 - 庄家方防守 / 抓分方进攻"""
        same = [c for c in self.hand if c.suit == lead_suit]
        has_score = any(c.rank in SCORE_RANKS for _, c in trick_so_far if _)
        level, ts = self.level, self.trump_suit

        if same:
            if has_score:
                # 有分牌
                _, best = trick_current_best(trick_so_far, level, ts, lead_suit)
                best_p = cp(best, level, ts)
                can_win = [c for c in same if cp(c, level, ts) > best_p]
                if can_win:
                    can_win.sort(key=lambda c: cp(c, level, ts))
                    card = can_win[0]
                else:
                    card = min(same, key=lambda c: RANK_ORDER.get(c.rank, 0))
            else:
                ns = [c for c in same if c.rank not in SCORE_RANKS]
                card = min(ns if ns else same, key=lambda c: RANK_ORDER.get(c.rank, 0))
        else:
            main = self._main_cards()
            all_main = self._all_main()

            if has_score:
                _, best = trick_current_best(trick_so_far, level, ts, lead_suit)
                best_p = cp(best, level, ts)

                if self.side == 'dealer':
                    # 庄家方：积极用主牌毙（节省资源）
                    can_win = [c for c in all_main if cp(c, level, ts) > best_p]
                    if can_win:
                        can_win.sort(key=lambda c: cp(c, level, ts))
                        card = can_win[0]
                    elif main:
                        main.sort(key=lambda c: RANK_ORDER.get(c.rank, 0))
                        card = main[0]
                    else:
                        off = [c for c in self.hand if not is_main(c, level, ts)]
                        card = min(off if off else self.hand, key=lambda c: RANK_ORDER.get(c.rank, 0))
                else:
                    # 抓分方：谨慎用主牌（只在能赢时出）
                    can_win = [c for c in all_main if cp(c, level, ts) > best_p]
                    if can_win:
                        can_win.sort(key=lambda c: cp(c, level, ts))
                        card = can_win[0]
                    else:
                        off = [c for c in self.hand if not is_main(c, level, ts)]
                        card = min(off if off else self.hand, key=lambda c: RANK_ORDER.get(c.rank, 0))
            elif is_last_trick and all_main:
                card = max(all_main, key=lambda c: cp(c, level, ts))
            else:
                off = [c for c in self.hand if not is_main(c, level, ts)]
                card = min(off if off else self.hand, key=lambda c: RANK_ORDER.get(c.rank, 0))

        self.hand.remove(card)
        return card

    def select_for_bottom(self, count):
        """选牌埋底/弃回：优先非分非主小牌"""
        def pri(c):
            return (int(is_main(c, self.level, self.trump_suit)),
                    int(c.rank in SCORE_RANKS),
                    RANK_ORDER.get(c.rank, 0))
        s = sorted(self.hand, key=pri)
        sel = s[:count]
        for c in sel: self.hand.remove(c)
        return sel

# ==================== 游戏记录 ====================

class RoundRecord:
    def __init__(self, rnd, dealer_pid, def_lvl, att_lvl):
        self.rnd = rnd
        self.dealer_pid = dealer_pid
        self.defender_level = def_lvl
        self.attacker_level = att_lvl
        self.level = def_lvl
        self.initial_hands = {}
        self.initial_bottom = []
        self.bright_pid = None; self.bright_card = None
        self.concealed_pid = None; self.concealed_card = None
        self.trump_suit = None
        self.trump_method = None
        self.buried_cards = []
        self.bottom_after_bury = []
        self.picked_from_bottom = []
        self.discarded_to_bottom = []
        self.bottom_after_pick = []
        self.tricks = []
        self.attacker_score = 0
        self.last_trick_winner_pid = None
        self.last_trick_winner_side = None
        self.last_trick_card = None
        self.base_up_att = 0
        self.bonus_up = 0
        self.final_up_att = 0
        self.final_up_def = 0
        self.result = ''
        self.result_title = ''
        self.logs = []
        self.dealer_team = []
        self.attacker_team = []
        self.game_over_check = False  # 标记本局是否检查过7

    def log(self, msg): self.logs.append(msg)

# ==================== 游戏引擎 ====================

class Game:
    def __init__(self):
        self.defender_level = 7
        self.attacker_level = 7
        self.dealer_pid = 0
        self.records = []
        self.game_over = False
        self.winner = None
        self.rnd = 0

    def run(self):
        while not self.game_over and self.rnd < 50:
            self.rnd += 1
            rec = self._play_round()
            self.records.append(rec)
        return self.records

    def _play_round(self):
        rec = RoundRecord(self.rnd, self.dealer_pid, self.defender_level, self.attacker_level)
        dt = [self.dealer_pid, (self.dealer_pid + 2) % 4]
        at = [(self.dealer_pid + 1) % 4, (self.dealer_pid + 3) % 4]
        rec.dealer_team = dt
        rec.attacker_team = at

        rec.log(f"=== 第{self.rnd}局 ===")
        rec.log(f"庄家方级牌={self.defender_level}, 抓分方级牌={self.attacker_level}, 庄家=玩家{self.dealer_pid+1}")
        rec.log(f"庄家阵营: 玩{dt[0]+1}、玩{dt[1]+1} | 抓分阵营: 玩{at[0]+1}、玩{at[1]+1}")

        hands, bottom = self._deal(rec)
        self._determine_trump(rec, hands)
        self._bury(rec, hands)
        if rec.concealed_pid is not None:
            self._pick_main(rec, hands)

        for pid in range(4):
            assert len(hands[pid]) == 12, f"玩{pid+1} 手牌 {len(hands[pid])} != 12"

        self._play_tricks(rec, hands, dt, at)
        self._settle(rec)

        rec.log(f"第{self.rnd}局结束 | 庄家方={self.defender_level} 抓分方={self.attacker_level}")
        return rec

    def _deal(self, rec):
        deck = create_deck()
        random.shuffle(deck)
        hands = [[] for _ in range(4)]
        bottom = []
        for i, card in enumerate(deck):
            (hands[i % 4] if i < 48 else bottom).append(card)
        rec.initial_hands = {p: list(h) for p, h in enumerate(hands)}
        rec.initial_bottom = list(bottom)
        rec.log(f"发牌完成 | 底牌: {cards_str(bottom)}")
        return hands, bottom

    def _determine_trump(self, rec, hands):
        dt, at = rec.dealer_team, rec.attacker_team
        lvl = rec.level
        scenario = random.choices(['bright', 'concealed', 'bottom'], weights=[45, 35, 20])[0]

        if scenario == 'bright':
            pid = random.choice(dt)
            lc = [c for c in hands[pid] if c.rank == lvl and c.suit in SUITS]
            if lc:
                card = random.choice(lc)
                rec.bright_pid, rec.bright_card = pid, card
                rec.trump_suit, rec.trump_method = card.suit, 'bright'
                rec.log(f"【亮牌】玩{pid+1} 亮 {card} → 主={SUIT_CN[card.suit]}")
                return

        if scenario == 'concealed':
            pid = random.choice(at)
            lc = [c for c in hands[pid] if c.rank == lvl and c.suit in SUITS]
            if lc:
                card = random.choice(lc)
                rec.concealed_pid, rec.concealed_card = pid, card
                rec.trump_method = 'concealed'
                rec.log(f"【闷牌】玩{pid+1} 闷一张级牌（花色待揭晓）")
                return

        fc = rec.initial_bottom[0]
        rec.trump_suit = fc.suit if fc.suit in SUITS else random.choice(SUITS)
        rec.trump_method = 'bottom_card'
        rec.log(f"【底牌首张定主】{fc} → 主={SUIT_CN.get(rec.trump_suit, rec.trump_suit)}")

    def _bury(self, rec, hands):
        pid = rec.dealer_pid
        bottom = list(rec.initial_bottom)
        bot = Bot(pid, hands[pid], 'dealer', rec.level, rec.trump_suit or '')

        n = random.randint(2, 5)
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

        take_back = temp_bottom[:n]
        new_bottom = temp_bottom[n:]
        assert len(new_bottom) == 6
        bot.hand.extend(take_back)
        hands[pid] = bot.hand

        rec.buried_cards, rec.bottom_after_bury = list(buried), list(new_bottom)
        bs = sum(SCORE_VALUES.get(c.rank, 0) for c in new_bottom)
        rec.log(f"【埋底】庄家（玩{pid+1}）埋 {cards_str(buried)}, 取回 {cards_str(take_back)}")
        rec.log(f"  埋底后底牌: {cards_str(new_bottom)} (分值={bs})")

    def _pick_main(self, rec, hands):
        pid = rec.concealed_pid
        ts = rec.concealed_card.suit
        rec.trump_suit = ts
        bottom = list(rec.bottom_after_bury)
        bot = Bot(pid, hands[pid], 'attacker', rec.level, ts)

        rec.log(f"【捡主】玩{pid+1} 翻开闷牌 {rec.concealed_card} → 主={SUIT_CN[ts]}")
        picked = [c for c in bottom if is_main(c, rec.level, ts)]
        if not picked:
            rec.log(f"  底牌无主牌，跳过"); rec.bottom_after_pick = list(bottom); return

        rec.picked_from_bottom = list(picked)
        bottom_rem = [c for c in bottom if c not in picked]
        bot.hand.extend(picked)
        discarded = bot.select_for_bottom(len(picked))
        new_bottom = bottom_rem + discarded
        assert len(new_bottom) == 6
        hands[pid] = list(bot.hand)
        rec.discarded_to_bottom = list(discarded)
        rec.bottom_after_pick = list(new_bottom)
        bs = sum(SCORE_VALUES.get(c.rank, 0) for c in new_bottom)
        rec.log(f"  拣出: {cards_str(picked)} | 弃回: {cards_str(discarded)}")
        rec.log(f"  捡主后底牌: {cards_str(new_bottom)} (分值={bs})")

    def _play_tricks(self, rec, hands, dt, at):
        bots = {}
        for pid in range(4):
            side = 'dealer' if pid in dt else 'attacker'
            bots[pid] = Bot(pid, hands[pid], side, rec.level, rec.trump_suit)

        leader = rec.dealer_pid

        for t in range(1, 13):
            trick = {'num': t, 'leader': leader, 'cards': [], 'winner': None,
                     'winner_side': None, 'score': 0, 'score_cards': []}
            lead_suit = None
            trick_so_far = []

            for pos in range(4):
                pid = (leader + pos) % 4
                if pos == 0:
                    card = bots[pid].lead()
                    lead_suit = card.suit
                else:
                    card = bots[pid].follow(lead_suit, trick_so_far, is_last_trick=(t == 12))
                trick['cards'].append((pid, card))
                trick_so_far.append((pid, card))

            best_pid, best_card = trick_current_best(trick['cards'], rec.level, rec.trump_suit, lead_suit)
            trick['winner'] = best_pid
            trick['winner_side'] = 'dealer' if best_pid in dt else 'attacker'

            for pid, card in trick['cards']:
                if card.rank in SCORE_RANKS:
                    trick['score_cards'].append(card)
                    trick['score'] += SCORE_VALUES[card.rank]

            rec.tricks.append(trick)
            ci = ' | '.join(f"玩{p+1}:{c}" for p, c in trick['cards'])
            rec.log(f"第{t}圈: 玩{leader+1}首出 → [{ci}] → 赢: 玩{best_pid+1}({best_card}) 分={trick['score']}")
            leader = best_pid

        rec.attacker_score = sum(t['score'] for t in rec.tricks)
        lt = rec.tricks[-1]
        rec.last_trick_winner_pid = lt['winner']
        rec.last_trick_winner_side = lt['winner_side']
        for pid, card in lt['cards']:
            if pid == lt['winner']: rec.last_trick_card = card; break
        rec.log(f"抓分方总分={rec.attacker_score}")

    def _settle(self, rec):
        sc = rec.attacker_score
        is_bottom = rec.last_trick_winner_side == 'attacker'

        if sc == 0:
            rec.result_title = '光头'; rec.base_up_att = 0; rec.final_up_def = 3
        elif sc <= 35:
            rec.result_title = '干受苦'; rec.base_up_att = 0; rec.final_up_def = 1
        elif sc <= 45:
            rec.result_title = '上台'; rec.base_up_att = 0; rec.final_up_def = 0
        else:
            rec.base_up_att = min((sc - 40) // 10 + 1, 6)
            rec.final_up_def = 0
            rec.result_title = f"升{rec.base_up_att}级"

        bonus = 0
        if is_bottom:
            bonus = 4 if (rec.last_trick_card and rec.last_trick_card.rank == '大王') else 3
        rec.bonus_up = bonus

        if is_bottom and sc < 40:
            rec.result_title = '干扣底'
            rec.final_up_def = 0; rec.base_up_att = 0; rec.bonus_up = 0

        rec.final_up_att = rec.base_up_att + bonus

        old_def, old_att = self.defender_level, self.attacker_level
        self.defender_level += rec.final_up_def
        self.attacker_level += rec.final_up_att

        rec.log(f"结算: 抓分={sc} 扣底={'是' if is_bottom else '否'} 庄方+{rec.final_up_def} 抓方+{rec.final_up_att}")
        rec.log(f"级牌: 庄方 {old_def}→{self.defender_level} | 抓方 {old_att}→{self.attacker_level}")

        self._check_over7(rec)

    def _check_over7(self, rec):
        rec.game_over_check = True

        # 庄家方过7 → 直接赢
        if self.defender_level > 7:
            rec.result_title = '庄家方胜🏆'
            self.game_over = True
            self.winner = '庄家方'
            rec.log(f"🏆 庄家方级牌 {self.defender_level} > 7，庄家方直接获胜！")
            return

        # 抓分方过7 → 特殊规则
        if self.attacker_level > 7:
            rec.result_title = '上台过7（需守庄）'
            rec.log(f"⚠️ 抓分方 {self.attacker_level} > 7，强制停在7，获得庄权，需再守庄一局")

            old_att = self.attacker_level
            self.attacker_level = 7  # 强制停在7

            # 抓分方拿庄 → 成为新的庄家方
            new_dealer = rec.attacker_team[0]
            # 新的庄家方级牌 = 7（原抓分方停在7）
            # 新的抓分方级牌 = 原庄家方级牌
            old_def = self.defender_level
            self.defender_level = 7
            self.attacker_level = old_def
            self.dealer_pid = new_dealer

            rec.log(f"庄家变更: → 玩{self.dealer_pid+1}")
            rec.log(f"级牌重置: 庄家方={self.defender_level} 抓分方={self.attacker_level}")

            # 检查上一局是否是"上台过7"（即这局是守庄局）
            # 守庄结果：如果庄家方（原抓分方）守庄成功（对方得分≤35），则原抓分方最终胜利
            if len(self.records) > 0:
                prev = self.records[-1]
                if prev.result_title == '上台过7（需守庄）':
                    # 这局是守庄局
                    if self.defender_level > 7:
                        self.game_over = True
                        self.winner = '抓分方🏆'
                        rec.log(f"🏆 原抓分方守庄成功（庄家方过7），最终胜利！")
                    elif rec.result_title in ('干受苦', '光头', '干扣底'):
                        self.game_over = True
                        self.winner = '抓分方🏆'
                        rec.log(f"🏆 原抓分方守庄成功（对方得分≤35），最终胜利！")
                    else:
                        rec.log(f"守庄失败，对方上台继续")
            return

        # 继续下一局
        if rec.final_up_att > 0 or rec.result_title in ('上台', '干扣底'):
            new_dealer = rec.attacker_team[0]
            if new_dealer != self.dealer_pid:
                self.dealer_pid = new_dealer
                self.defender_level, self.attacker_level = self.attacker_level, self.defender_level
                rec.log(f"庄家变更: → 玩{self.dealer_pid+1} | 级牌: 庄方={self.defender_level} 抓方={self.attacker_level}")


# ==================== Excel ====================

def save_excel(records, game, path):
    wb = Workbook()
    tf = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    tfont = Font(size=14, bold=True, color="FFFFFF")
    hf = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    hfont = Font(bold=True, color="FFFFFF")
    sf = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
    sfont = Font(bold=True, size=11)

    # ====== Sheet1: 总览 ======
    ws = wb.active; ws.title = "游戏总览"
    ws.merge_cells('A1:P1')
    c = ws['A1']; c.value = f"一副牌升级游戏模拟（过7）"; c.font = tfont; c.fill = tf; c.alignment = Alignment(horizontal='center')
    ws.merge_cells('A2:P2')
    c = ws['A2']; c.value = f"生成: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 共{len(records)}局 | 胜方: {game.winner or '未完成'}"; c.font = Font(italic=True)

    hdrs = ['局数','庄家','庄方级(前)','抓方级(前)','本局级',
            '定主方式','亮牌/闷牌','主花色',
            '抓分','扣底','扣底牌',
            '抓方升级','庄方升级','庄方级(后)','抓方级(后)','结果']
    r = 4
    for col, h in enumerate(hdrs, 1):
        c = ws.cell(row=r, column=col, value=h)
        c.font = hfont; c.fill = hf; c.alignment = Alignment(horizontal='center')

    cur_def, cur_att = 7, 7
    for i, rec in enumerate(records):
        r = 5 + i
        pre_def, pre_att = cur_def, cur_att

        if rec.trump_method == 'bright':
            tm, td = '亮牌', f"玩{rec.bright_pid+1}亮{rec.bright_card}"
        elif rec.trump_method == 'concealed':
            tm, td = '闷牌', f"玩{rec.concealed_pid+1}闷{rec.concealed_card}"
        else:
            tm, td = '底牌首张', '底牌首张定主'
        ts = SUIT_CN.get(rec.trump_suit, rec.trump_suit or '—')
        ib = rec.last_trick_winner_side == 'attacker' if rec.last_trick_winner_side else False

        cur_def += rec.final_up_def
        cur_att += rec.final_up_att

        vals = [rec.rnd, f"玩{rec.dealer_pid+1}", pre_def, pre_att, rec.level,
                tm, td, ts, rec.attacker_score,
                '是' if ib else '否', str(rec.last_trick_card or '—'),
                f"+{rec.final_up_att}" if rec.final_up_att else 0,
                f"+{rec.final_up_def}" if rec.final_up_def else 0,
                cur_def, cur_att, rec.result_title]

        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v); c.alignment = Alignment(horizontal='center')
        if i == len(records) - 1:
            for col in range(1, len(hdrs)+1):
                ws.cell(row=r, column=col).fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")

    for col in range(1, len(hdrs)+1):
        ws.column_dimensions[get_column_letter(col)].width = max(12, len(hdrs[col-1])*2)

    # ====== Sheet2: 每局详情 ======
    ws2 = wb.create_sheet("每局详情")
    row = 1

    for rec in records:
        ws2.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)
        c = ws2.cell(row=row, column=1, value=f"═══ 第{rec.rnd}局 ─ {rec.result_title} ═══")
        c.font = tfont; c.fill = tf; row += 1

        for label, val in [
            ("庄家", f"玩家{rec.dealer_pid+1}"),
            ("庄家方级牌", str(rec.defender_level)),
            ("抓分方级牌", str(rec.attacker_level)),
            ("本局级牌", str(rec.level)),
            ("庄家阵营", f"玩家{rec.dealer_team[0]+1}、玩家{rec.dealer_team[1]+1}"),
            ("抓分阵营", f"玩家{rec.attacker_team[0]+1}、玩家{rec.attacker_team[1]+1}"),
            ("定主方式", rec.trump_method or '—'),
            ("主花色", SUIT_CN.get(rec.trump_suit, rec.trump_suit or '—') if rec.trump_suit else '—'),
        ]:
            c = ws2.cell(row=row, column=1, value=label); c.font = sfont
            ws2.cell(row=row, column=3, value=val); row += 1

        if rec.bright_pid is not None:
            c = ws2.cell(row=row, column=1, value="⭐ 亮牌"); c.font = sfont; c.fill = sf; row += 1
            ws2.cell(row=row, column=1, value="亮牌玩家"); ws2.cell(row=row, column=2, value=f"玩家{rec.bright_pid+1}")
            ws2.cell(row=row, column=3, value="亮出的牌"); ws2.cell(row=row, column=4, value=str(rec.bright_card)); row += 1
        if rec.concealed_pid is not None:
            c = ws2.cell(row=row, column=1, value="🃏 闷牌"); c.font = sfont; c.fill = sf; row += 1
            ws2.cell(row=row, column=1, value="闷牌玩家"); ws2.cell(row=row, column=2, value=f"玩家{rec.concealed_pid+1}")
            ws2.cell(row=row, column=3, value="闷的牌"); ws2.cell(row=row, column=4, value=str(rec.concealed_card)); row += 1

        c = ws2.cell(row=row, column=1, value="📋 初始手牌"); c.font = sfont; c.fill = sf; row += 1
        for pid in range(4):
            ws2.cell(row=row, column=1, value=f"玩家{pid+1}")
            ws2.cell(row=row, column=2, value=cards_str(rec.initial_hands.get(pid, [])))
            ws2.merge_cells(start_row=row, start_column=2, end_row=row, end_column=8); row += 1

        c = ws2.cell(row=row, column=1, value="📦 底牌信息"); c.font = sfont; c.fill = sf; row += 1
        ws2.cell(row=row, column=1, value="初始底牌"); ws2.cell(row=row, column=2, value=cards_str(rec.initial_bottom))
        ws2.merge_cells(start_row=row, start_column=2, end_row=row, end_column=8); row += 1

        if rec.buried_cards:
            ws2.cell(row=row, column=1, value="庄家埋入"); ws2.cell(row=row, column=2, value=cards_str(rec.buried_cards))
            ws2.cell(row=row, column=3, value="埋底后底牌"); ws2.cell(row=row, column=4, value=cards_str(rec.bottom_after_bury))
            bs = sum(SCORE_VALUES.get(c.rank,0) for c in rec.bottom_after_bury)
            ws2.cell(row=row, column=5, value=f"分值={bs}")
            ws2.merge_cells(start_row=row, start_column=2, end_row=row, end_column=3); row += 1

        if rec.picked_from_bottom:
            ws2.cell(row=row, column=1, value="拣出主牌"); ws2.cell(row=row, column=2, value=cards_str(rec.picked_from_bottom))
            ws2.cell(row=row, column=3, value="弃回底牌"); ws2.cell(row=row, column=4, value=cards_str(rec.discarded_to_bottom))
            ws2.cell(row=row, column=5, value="捡主后底牌"); ws2.cell(row=row, column=6, value=cards_str(rec.bottom_after_pick)); row += 1

        c = ws2.cell(row=row, column=1, value="🃏 出牌记录"); c.font = sfont; c.fill = sf; row += 1
        for tr in rec.tricks:
            cd = ' → '.join(f"玩{p+1}:{c}" for p, c in tr['cards'])
            ws2.cell(row=row, column=1, value=f"第{tr['num']}圈")
            ws2.cell(row=row, column=2, value=cd)
            ws2.merge_cells(start_row=row, start_column=2, end_row=row, end_column=6)
            ws2.cell(row=row, column=7, value=f"玩{tr['winner']+1}")
            ws2.cell(row=row, column=8, value=tr['score']); row += 1

        c = ws2.cell(row=row, column=1, value="📊 结算"); c.font = sfont; c.fill = sf; row += 1
        ib = rec.last_trick_winner_side == 'attacker' if rec.last_trick_winner_side else False
        for label, val in [
            ("抓分方得分", str(rec.attacker_score)),
            ("是否扣底", "是" if ib else "否"),
            ("扣底牌", str(rec.last_trick_card) if rec.last_trick_card else "—"),
            ("基础升级 抓方", f"+{rec.base_up_att}" if rec.base_up_att else "0"),
            ("扣底加成", f"+{rec.bonus_up}" if rec.bonus_up else "无"),
            ("总升级 抓方", f"+{rec.final_up_att}"),
            ("总升级 庄方", f"+{rec.final_up_def}"),
            ("结果", rec.result_title),
        ]:
            ws2.cell(row=row, column=1, value=label).font = Font(bold=True)
            ws2.cell(row=row, column=3, value=val); row += 1

        c = ws2.cell(row=row, column=1, value="📝 操作日志"); c.font = sfont; c.fill = sf; row += 1
        for log in rec.logs:
            ws2.cell(row=row, column=1, value=log)
            ws2.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8); row += 1

        row += 2

    for col in range(1, 9):
        ws2.column_dimensions[get_column_letter(col)].width = 18

    # ====== Sheet3: 出牌记录总表 ======
    ws3 = wb.create_sheet("出牌记录总表")
    ws3.merge_cells('A1:K1')
    c = ws3['A1']; c.value = "出牌记录总表"; c.font = tfont; c.fill = tf; c.alignment = Alignment(horizontal='center')

    th = ['局数','圈数','首出','玩1','玩2','玩3','玩4','赢家','得分','赢家阵营']
    r = 3
    for col, h in enumerate(th, 1):
        c = ws3.cell(row=r, column=col, value=h)
        c.font = hfont; c.fill = hf; c.alignment = Alignment(horizontal='center')

    r = 4
    for rec in records:
        for tr in rec.tricks:
            cd = {p: str(c) for p, c in tr['cards']}
            vals = [rec.rnd, tr['num'], f"玩{tr['leader']+1}",
                    cd.get(0,''), cd.get(1,''), cd.get(2,''), cd.get(3,''),
                    f"玩{tr['winner']+1}", tr['score'],
                    '庄家方' if tr['winner_side']=='dealer' else '抓分方']
            for col, v in enumerate(vals, 1):
                ws3.cell(row=r, column=col, value=v).alignment = Alignment(horizontal='center')
            r += 1

    for col in range(1, len(th)+1):
        ws3.column_dimensions[get_column_letter(col)].width = 15

    wb.save(path)
    print(f"✅ Excel: {path}")

# ==================== 主程序 ====================

def main():
    print("🎮 一副牌升级游戏模拟器")
    print("=" * 50)

    game = Game()
    records = game.run()

    print(f"\n游戏结束! 共{len(records)}局 | 胜方: {game.winner or '未完成'}")
    print(f"最终: 庄家方={game.defender_level} 抓分方={game.attacker_level}")

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = os.path.join(os.path.dirname(__file__), f'一副牌升级游戏模拟_{ts}.xlsx')
    save_excel(records, game, path)

    print("\n📋 各局结果:")
    for rec in records:
        print(f"  第{rec.rnd}局: 庄家=玩{rec.dealer_pid+1}, 抓分={rec.attacker_score}, {rec.result_title}")
    print(f"\n🏆 胜方: {game.winner or '未完成（50局上限）'}")

if __name__ == '__main__':
    main()
