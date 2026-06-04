import os, sys

os.chdir(r'c:\clawproject\singledeck-shengji')

with open('gui.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''        # 首出者手牌为空则立即结算（防止空手出牌导致数量发散）
        if not bots[self.trick_leader].hand:
            self._settle_and_continue()
            return

        # 全员空手则立即结算
        if not any(bots[p].hand for p in range(4)):
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
            played_so_far.append((pid, card_list))'''

new = '''        # 任一玩家手牌为空则立即结算（防止出牌数量不一致）
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
            played_so_far.append((pid, card_list))'''

if old in content:
    content = content.replace(old, new, 1)
    with open('gui.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK - replaced')
elif '任一玩家' in content:
    print('ALREADY PATCHED')
else:
    print('NOT FOUND - content sample around line 681:')
    lines = content.split('\n')
    for i in range(679, min(710, len(lines))):
        print(f'{i+1}: {lines[i]}')
