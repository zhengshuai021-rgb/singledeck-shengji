#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核心规则单元测试"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import unittest
from game import (
    Card, create_deck, is_main, cp, compare_cards,
    compare_trick_patterns, find_hongs, find_510k, find_zhas,
    level_up, LEVEL_CYCLE, Game, RoundRecord
)


class TestCard(unittest.TestCase):
    def test_joker_repr(self):
        self.assertEqual(str(Card('王', '大王')), '大王')
        self.assertEqual(str(Card('王', '小王')), '小王')

    def test_normal_repr(self):
        self.assertEqual(str(Card('♠', 'A')), '♠A')


class TestIsMain(unittest.TestCase):
    def test_jokers_always_main(self):
        self.assertTrue(is_main(Card('王', '大王'), '7', '♠'))
        self.assertTrue(is_main(Card('王', '小王'), '7', '♠'))

    def test_heart_3_main(self):
        self.assertTrue(is_main(Card('♥', '3'), '7', '♠'))
        # 红桃3是常主；其他花色3不是主（除非该花色恰好是主花色）
        self.assertFalse(is_main(Card('♠', '3'), '7', '♥'))

    def test_level_main(self):
        self.assertTrue(is_main(Card('♠', '7'), '7', '♣'))
        self.assertFalse(is_main(Card('♠', '8'), '7', '♣'))

    def test_trump_suit_main(self):
        self.assertTrue(is_main(Card('♥', '5'), '7', '♥'))
        self.assertFalse(is_main(Card('♣', '5'), '7', '♥'))


class TestCompareCards(unittest.TestCase):
    def test_main_beats_off(self):
        c1 = Card('♥', '5')   # 主花色
        c2 = Card('♠', 'A')   # 副牌
        self.assertEqual(compare_cards(c1, c2, '7', '♥', '♠'), 1)
        self.assertEqual(compare_cards(c2, c1, '7', '♥', '♠'), -1)

    def test_same_suit_compare_rank(self):
        c1 = Card('♠', 'A')
        c2 = Card('♠', 'K')
        self.assertEqual(compare_cards(c1, c2, '7', '♥', '♠'), 1)

    def test_level_beats_trump_suit(self):
        c1 = Card('♣', '7')   # 级牌
        c2 = Card('♥', 'A')   # 主花色
        self.assertEqual(compare_cards(c1, c2, '7', '♥', '♥'), 1)


class TestPatterns(unittest.TestCase):
    def test_find_510k(self):
        hand = [Card('♠', '5'), Card('♠', '10'), Card('♠', 'K'), Card('♥', '2')]
        result = find_510k(hand, '♠')
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 3)

    def test_find_hong(self):
        hand = [Card('♠', '5'), Card('♥', '5'), Card('♣', '5'), Card('♦', '5')]
        result = find_hongs(hand)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], '5')

    def test_find_zha(self):
        hand = [Card('♠', 'A'), Card('♠', '5'), Card('♥', '5'), Card('♣', '5')]
        result = find_zhas(hand)
        self.assertEqual(len(result), 1)


class TestLevelUp(unittest.TestCase):
    def test_level_cycle(self):
        self.assertEqual(level_up('7', 1), '8')
        self.assertEqual(level_up('A', 1), '2')
        self.assertEqual(level_up('6', 1), '7')  # 完整循环


class TestGameSettlement(unittest.TestCase):
    def test_zero_score_dealer_gets_three(self):
        g = Game(total_rounds=1)
        g.rnd = 1
        rec = RoundRecord(1, 0, '7', '7')
        rec.dealer_team = [0, 2]
        rec.attacker_team = [1, 3]
        rec.tricks = []
        rec.attacker_score = 0
        rec.last_trick_winner_side = 'dealer'
        g._settle(rec)
        self.assertEqual(rec.final_up_def, 3)
        self.assertEqual(rec.final_up_att, 0)

    def test_attacker_over_50_upgrades(self):
        g = Game(total_rounds=1)
        g.rnd = 1
        rec = RoundRecord(1, 0, '7', '7')
        rec.dealer_team = [0, 2]
        rec.attacker_team = [1, 3]
        rec.tricks = []
        rec.attacker_score = 60
        rec.last_trick_winner_side = 'attacker'
        g._settle(rec)
        self.assertGreater(rec.final_up_att, 0)


if __name__ == '__main__':
    unittest.main()
