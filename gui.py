#!/usr/bin/env python3
"""一副牌升级 GUI 模拟器 — Tkinter Canvas 实现"""
import os, sys
# 抑制 libpng iCCP 警告
_old_write = sys.stderr.write
def _filtered(s):
    if 'iCCP' not in s and 'libpng' not in s:
        _old_write(s)
sys.stderr.write = _filtered

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import random
from datetime import datetime

from game import (
    create_deck, Card, Bot, RoundRecord,
    SUITS, SUIT_CN, SCORE_RANKS, SCORE_VALUES, RANK_ORDER,
    cp, is_main, cards_str,
    compare_trick_patterns, max_card_in_trick,
    level_up, level_idx,
    find_hongs, find_510k, find_zhas,
    count_hand_patterns, check_deal_requirements,
    LEVEL_CYCLE, save_excel
)

# ==================== GUI 常量 ====================

CARD_W, CARD_H = 62, 88
CARD_R = 8
SUIT_COLORS = {'♠': '#1a1a2e', '♥': '#c0392b', '♣': '#1a1a2e', '♦': '#c0392b', '王': '#8e44ad'}
BG_COLOR = '#0d6b3e'
FELT_COLOR = '#0f7a44'
PANEL_BG = '#2c3e50'
TEXT_LIGHT = '#ecf0f1'
BUTTON_BG = '#34495e'
BUTTON_ACTIVE = '#2980b9'

# ==================== 牌面渲染 ====================

def draw_card(canvas, x, y, card, highlight=False, small=False):
    """在 Canvas 上绘制一张扑克牌"""
    w, h, r = (52, 74, 7) if small else (CARD_W, CARD_H, CARD_R)
    color = SUIT_COLORS.get(card.suit, SUIT_COLORS['王'])

    # 圆角矩形: 4个角用 arc, 中间用 rect
    d = 2 * r
    parts = [
        canvas.create_rectangle(x + r, y, x + w - r, y + h, fill='white', outline='', tags='card'),
        canvas.create_rectangle(x, y + r, x + w, y + h - r, fill='white', outline='', tags='card'),
        canvas.create_arc(x, y, x + d, y + d, start=90, extent=90, fill='white', outline='', tags='card'),
        canvas.create_arc(x + w - d, y, x + w, y + d, start=0, extent=90, fill='white', outline='', tags='card'),
        canvas.create_arc(x, y + h - d, x + d, y + h, start=180, extent=90, fill='white', outline='', tags='card'),
        canvas.create_arc(x + w - d, y + h - d, x + w, y + h, start=270, extent=90, fill='white', outline='', tags='card'),
    ]

    outline_color = '#e74c3c' if highlight else '#bdc3c7'
    canvas.create_rectangle(x + r, y, x + w - r, y + h, fill='', outline=outline_color, width=2 if highlight else 1, tags='card')
    canvas.create_rectangle(x, y + r, x + w, y + h - r, fill='', outline=outline_color, width=2 if highlight else 1, tags='card')
    canvas.create_arc(x, y, x + d, y + d, start=90, extent=90, fill='', outline=outline_color, width=2 if highlight else 1, style='arc', tags='card')
    canvas.create_arc(x + w - d, y, x + w, y + d, start=0, extent=90, fill='', outline=outline_color, width=2 if highlight else 1, style='arc', tags='card')
    canvas.create_arc(x, y + h - d, x + d, y + h, start=180, extent=90, fill='', outline=outline_color, width=2 if highlight else 1, style='arc', tags='card')
    canvas.create_arc(x + w - d, y + h - d, x + w, y + h, start=270, extent=90, fill='', outline=outline_color, width=2 if highlight else 1, style='arc', tags='card')

    # 文字
    rank = card.rank
    suit = card.suit
    cx, cy = x + w // 2, y + h // 2

    if card.rank in ('大王', '小王'):
        joker_color = '#c0392b' if card.rank == '大王' else '#1a1a2e'
        fs = 16 if small else 22
        canvas.create_text(cx, cy - 2, text=card.rank, fill=joker_color,
                          font=('Microsoft YaHei', fs, 'bold'), tags='card')
    else:
        canvas.create_text(cx, cy, text=f"{rank}{suit}", fill=color,
                          font=('Segoe UI Symbol', 26 if small else 32), tags='card')


def draw_card_back(canvas, x, y, small=False):
    """牌背"""
    w, h, r = (52, 74, 7) if small else (CARD_W, CARD_H, CARD_R)
    d = 2 * r
    parts = [
        canvas.create_rectangle(x + r, y, x + w - r, y + h, fill='#2c3e50', outline='', tags='card'),
        canvas.create_rectangle(x, y + r, x + w, y + h - r, fill='#2c3e50', outline='', tags='card'),
        canvas.create_arc(x, y, x + d, y + d, start=90, extent=90, fill='#2c3e50', outline='', tags='card'),
        canvas.create_arc(x + w - d, y, x + w, y + d, start=0, extent=90, fill='#2c3e50', outline='', tags='card'),
        canvas.create_arc(x, y + h - d, x + d, y + h, start=180, extent=90, fill='#2c3e50', outline='', tags='card'),
        canvas.create_arc(x + w - d, y + h - d, x + w, y + h, start=270, extent=90, fill='#2c3e50', outline='', tags='card'),
    ]
    canvas.create_rectangle(x + 4, y + 4, x + w - 4, y + h - 4, fill='', outline='#3498db', width=2, tags='card')
    canvas.create_text(x + w // 2, y + h // 2, text='🂠', fill='#3498db',
                      font=('Segoe UI Symbol', 28), tags='card')


# ==================== GUI 主类 ====================

class GameGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("一副牌升级 · GUI 模拟器")
        self.root.geometry("1280x900")
        self.root.configure(bg=BG_COLOR)
        self.root.resizable(False, False)

        # 游戏状态
        self.running = False
        self.step_mode = True
        self.step_delay = 400
        self.game = None
        self.engine = None
        self.seed = None
        self.deal_requirements = {}

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
        self._after_id = None
        self.dealer_pid = 0
        self.defender_level = '7'
        self.attacker_level = '7'
        self.team_a_level = '7'
        self.team_b_level = '7'
        self.team_a_cumulative_steps = 0
        self.team_b_cumulative_steps = 0
        self.defending_team = None
        self.records = []
        self.round_records = []
        self.total_rounds = None
        self.current_round = 1
        self.round_starts_at = 1
        self.rnd = 0
        self.game_over_flag = False
        self.winner = None

        self._build_ui()

    def _build_ui(self):
        # 顶部控制栏
        top_frame = tk.Frame(self.root, bg=PANEL_BG, height=50)
        top_frame.pack(fill=tk.X, side=tk.TOP)
        top_frame.pack_propagate(False)

        tk.Label(top_frame, text="🎮 一副牌升级", bg=PANEL_BG, fg=TEXT_LIGHT,
                font=('Microsoft YaHei', 16, 'bold')).pack(side=tk.LEFT, padx=15, pady=8)

        self.btn_start = tk.Button(top_frame, text="▶ 开始", command=self.init_game,
                                    bg='#27ae60', fg='white', font=('Microsoft YaHei', 11),
                                    width=10, relief=tk.FLAT, cursor='hand2')
        self.btn_start.pack(side=tk.LEFT, padx=5, pady=8)

        self.btn_step = tk.Button(top_frame, text="▶ 下一步", command=self.step_forward,
                                   bg='#2980b9', fg='white', font=('Microsoft YaHei', 11),
                                   width=10, relief=tk.FLAT, cursor='hand2', state=tk.DISABLED)
        self.btn_step.pack(side=tk.LEFT, padx=5, pady=8)

        self.btn_auto = tk.Button(top_frame, text="▶▶ 自动", command=self.toggle_auto,
                                   bg=BUTTON_BG, fg=TEXT_LIGHT, font=('Microsoft YaHei', 11),
                                   width=10, relief=tk.FLAT, cursor='hand2', state=tk.DISABLED)
        self.btn_auto.pack(side=tk.LEFT, padx=5, pady=8)

        self.btn_export = tk.Button(top_frame, text="📊 导出", command=self.export_excel,
                                     bg=BUTTON_BG, fg=TEXT_LIGHT, font=('Microsoft YaHei', 11),
                                     width=10, relief=tk.FLAT, cursor='hand2', state=tk.DISABLED)
        self.btn_export.pack(side=tk.LEFT, padx=5, pady=8)

        # 设置区
        tk.Label(top_frame, text=" 延迟:", bg=PANEL_BG, fg=TEXT_LIGHT,
                font=('Microsoft YaHei', 9)).pack(side=tk.LEFT, padx=(20, 2))
        self.speed_var = tk.StringVar(value='中速')
        speed_combo = ttk.Combobox(top_frame, textvariable=self.speed_var,
                                    values=['慢速', '中速', '快速', '极速'],
                                    state='readonly', width=6)
        speed_combo.pack(side=tk.LEFT, padx=2)
        speed_combo.bind('<<ComboboxSelected>>', self._on_speed_change)

        # 牌型配置
        tk.Label(top_frame, text="牌型:", bg=PANEL_BG, fg=TEXT_LIGHT,
                font=('Microsoft YaHei', 9)).pack(side=tk.LEFT, padx=(10, 2))
        self.hong_var = tk.StringVar(value='')
        for label, var in [('轰', self.hong_var)]:
            e = tk.Entry(top_frame, textvariable=var, width=4, font=('Arial', 9),
                        justify='center', relief=tk.FLAT, bg='#3d566e', fg='white', insertbackground='white')
            e.pack(side=tk.LEFT, padx=1)
            tk.Label(top_frame, text=label, bg=PANEL_BG, fg='#bdc3c7', font=('Microsoft YaHei', 8)).pack(side=tk.LEFT)

        self.seed_var = tk.StringVar(value='')
        tk.Label(top_frame, text="种子:", bg=PANEL_BG, fg=TEXT_LIGHT,
                font=('Microsoft YaHei', 9)).pack(side=tk.LEFT, padx=(10, 2))
        tk.Entry(top_frame, textvariable=self.seed_var, width=6, font=('Arial', 9),
                justify='center', relief=tk.FLAT, bg='#3d566e', fg='white', insertbackground='white').pack(side=tk.LEFT)

        self.rounds_var = tk.StringVar(value='')
        tk.Label(top_frame, text="轮数:", bg=PANEL_BG, fg=TEXT_LIGHT,
                font=('Microsoft YaHei', 9)).pack(side=tk.LEFT, padx=(10, 2))
        tk.Entry(top_frame, textvariable=self.rounds_var, width=4, font=('Arial', 9),
                justify='center', relief=tk.FLAT, bg='#3d566e', fg='white', insertbackground='white').pack(side=tk.LEFT)

        # 主画布
        self.canvas = tk.Canvas(self.root, bg=FELT_COLOR, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # 底部状态栏
        self.status_bar = tk.Label(self.root, text="就绪 | 点击「开始」启动游戏",
                                    bg=PANEL_BG, fg=TEXT_LIGHT,
                                    font=('Microsoft YaHei', 10), anchor='w', height=1)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM, padx=0, pady=0)

    # ==================== 控制逻辑 ====================

    def _on_speed_change(self, event=None):
        speeds = {'慢速': 800, '中速': 400, '快速': 150, '极速': 30}
        self.step_delay = speeds.get(self.speed_var.get(), 400)

    def _parse_requirements(self):
        req = {}
        if self.hong_var.get().strip():
            req['hong'] = self._parse_one(self.hong_var.get().strip())
        return req

    def _parse_one(self, val):
        parts = val.split(':')
        lo = int(parts[0])
        hi = int(parts[1]) if len(parts) > 1 else lo
        return (lo, hi)

    def init_game(self):
        if self.running:
            return
        self.running = True
        self.step_mode = True
        self.game_over_flag = False
        self.winner = None

        seed_str = self.seed_var.get().strip()
        self.seed = int(seed_str) if seed_str else None
        if self.seed is not None:
            random.seed(self.seed)

        rounds_str = self.rounds_var.get().strip()
        self.total_rounds = int(rounds_str) if rounds_str else None
        self.deal_requirements = self._parse_requirements()
        self._on_speed_change()

        self.dealer_pid = random.randint(0, 3)
        self.defender_level = '7'
        self.attacker_level = '7'
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

        self.btn_start.config(state=tk.DISABLED)
        self.btn_step.config(state=tk.NORMAL)
        self.btn_auto.config(state=tk.NORMAL)
        self.btn_export.config(state=tk.NORMAL)

        self._step_next_round()
        self._render_all()
        self._set_status("步进模式 | 点击「下一步」推进")

    def step_forward(self):
        if not self.running or self.game_over_flag:
            return
        self.step_mode = True
        self.btn_step.config(state=tk.NORMAL)
        if self.btn_auto['state'] == tk.DISABLED:
            self.btn_auto.config(state=tk.NORMAL)
        self.btn_auto.config(text="▶▶ 自动", bg=BUTTON_BG, fg=TEXT_LIGHT)
        self._do_one_step()

    def toggle_auto(self):
        if not self.running or self.game_over_flag:
            return
        if self.step_mode:
            self._start_auto()
        else:
            self._stop_auto()

    def _start_auto(self):
        self.step_mode = False
        self.btn_step.config(state=tk.DISABLED)
        self.btn_auto.config(text="⏸ 暂停", bg='#e67e22', fg='white')
        self._set_status("自动模式 | 持续播放中…")
        self._after_id = self.root.after(self.step_delay, self._tick)

    def _stop_auto(self):
        self.step_mode = True
        self.btn_step.config(state=tk.NORMAL)
        self.btn_auto.config(text="▶▶ 自动", bg=BUTTON_BG, fg=TEXT_LIGHT)
        if self._after_id:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        self._set_status("步进模式 | 已暂停自动")

    def _do_one_step(self):
        if self.game_over_flag:
            self._finish_game()
            return

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

        self._render_all()
        if self.game_over_flag:
            self._finish_game()

    def export_excel(self):
        if not self.records:
            messagebox.showinfo("导出", "暂无数据可导出")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile=f"升级GUI_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        )
        if path:
            g = type('G', (), {'winner': self.winner, 'round_records': self.round_records})()
            save_excel(self.records, g, path)

    # ==================== 游戏步骤引擎 ====================

    def _step_next_round(self):
        """开始新一局"""
        if self.game_over_flag:
            self._finish_game()
            return

        self.rnd += 1
        dt = [self.dealer_pid, (self.dealer_pid + 2) % 4]
        at = [(self.dealer_pid + 1) % 4, (self.dealer_pid + 3) % 4]
        self.dt = dt
        self.at = at
        self.rec = RoundRecord(self.rnd, self.dealer_pid, self.defender_level, self.attacker_level)
        self.rec.dealer_team = dt
        self.rec.attacker_team = at
        self.rec.level = self.defender_level

        self._set_status(f"第 {self.rnd} 局 | 庄家方={self.defender_level} 抓分方={self.attacker_level}")
        self.bots = {}
        self.trick_idx = 0
        self.current_trick = None
        self._deal()
        self.engine_state = 'trump'
        self._render_all()

    def _deal(self):
        for attempt in range(100000):
            deck = create_deck()
            random.shuffle(deck)
            hands = [[] for _ in range(4)]
            bottom = []
            for i, card in enumerate(deck):
                (hands[i % 4] if i < 48 else bottom).append(card)
            if not self.deal_requirements or check_deal_requirements(hands, self.deal_requirements):
                self.hands = hands
                self.bottom = bottom
                self.rec.initial_hands = {p: list(h) for p, h in enumerate(hands)}
                self.rec.initial_bottom = list(bottom)
                return
        self.hands = hands
        self.bottom = bottom
        self.rec.initial_hands = {p: list(h) for p, h in enumerate(hands)}
        self.rec.initial_bottom = list(bottom)

    def _do_trump_stage(self):
        """定主阶段"""
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

        if rec.trump_method == 'concealed' and rec.concealed_pid is not None \
                and rec.concealed_pid in dt and rec.concealed_pid == self.dealer_pid:
            rec.bright_pid = rec.concealed_pid
            rec.bright_card = rec.concealed_card
            rec.trump_suit = rec.concealed_card.suit
            rec.trump_method = 'bright'
            rec.concealed_pid = None
            rec.concealed_card = None

        self.engine_state = 'bury'
        self._set_status(self._trump_label())

    def _trump_label(self):
        rec = self.rec
        if rec.trump_method == 'bright':
            return f"⭐ 亮牌定主: 玩{rec.bright_pid+1}亮{rec.bright_card} → {SUIT_CN.get(rec.trump_suit,'')}"
        elif rec.trump_method == 'concealed':
            return f"🃏 闷牌: 玩{rec.concealed_pid+1}暗扣级牌（花色待揭晓）"
        return f"🎲 底牌首张定主 → {SUIT_CN.get(rec.trump_suit,'')}"

    def _do_bury_stage(self):
        """埋底阶段"""
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
        bs = sum(SCORE_VALUES.get(c.rank, 0) for c in new_bottom)
        self._set_status(f"📦 埋底完成 | 庄家埋{len(buried)}张取回{len(take_back)}张 | 底牌{bs}分")

        if rec.concealed_pid is not None:
            self.engine_state = 'pick'
        else:
            self._finalize_prep()

    def _do_pick_stage(self):
        """捡主阶段"""
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
                self._set_status(f"🔍 捡主: 玩{pid+1}翻开{rec.concealed_card} → {SUIT_CN.get(ts,'')}")
            else:
                self._set_status(f"⚠️ 捡主后底牌{new_bs}分>35，放弃捡主")
        else:
            self._set_status(f"🔍 捡主: 底牌无主牌，跳过")

        self._finalize_prep()

    def _finalize_prep(self):
        """准备完成，接下来出牌"""
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
        self._set_status(f"开始出牌 | 主花色={SUIT_CN.get(rec.trump_suit,'')}")

    def _play_next_trick(self):
        """播放下一圈"""
        if self.trick_idx >= 12:
            self._settle_and_continue()
            return

        dt, at = self.dt, self.at
        rec = self.rec
        bots = self.bots

        # 首出者手牌为空则立即结算（防止空手出牌导致数量发散）
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
        self.current_trick = trick
        self.trick_leader = best_pid
        self.trick_idx = t

        # 本轮结束后，若任一方手牌为空则立即结算（防止牌数不一致）
        if any(len(bots[p].hand) == 0 for p in range(4)):
            self._settle_and_continue()
            return

        self._set_status(f"第 {self.rnd} 局 | 第 {t} 圈 | 赢家: 玩家{best_pid+1} (+{trick['score']}分)")
        self._render_all()

    def _settle_and_continue(self):
        """结算当前局"""
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

        self.defender_level = level_up(self.defender_level, rec.final_up_def)
        self.attacker_level = level_up(self.attacker_level, rec.final_up_att)

        # 过7判定
        def has_over7(lvl):
            return level_idx(lvl) > 0

        dealer_is_a = self.dealer_pid in (0, 2)
        dealer_lvl = self.team_a_level if dealer_is_a else self.team_b_level
        attacker_lvl = self.team_b_level if dealer_is_a else self.team_a_level
        dlabel = '队伍A' if dealer_is_a else '队伍B'
        alabel = '队伍B' if dealer_is_a else '队伍A'

        if has_over7(dealer_lvl):
            rec.result_title = f'{dlabel}过7🏆'
            rec.round_ended = True
            rec.round_winner = dlabel
            if not self.total_rounds:
                self.game_over_flag = True
                self.winner = f'{dlabel}（庄家方）'
            else:
                self._reset_round_state()
        elif has_over7(attacker_lvl):
            self.team_b_level = '7'
            self.team_a_level = '7'
            new_dealer = (self.dealer_pid + 1) % 4 if self.dealer_pid % 2 == 0 else (self.dealer_pid + 3) % 4
            self.dealer_pid = new_dealer
            self.defender_level = '7'
            self.attacker_level = '7'
            rec.result_title = f'{alabel}过7🏆'
            rec.round_ended = True
            rec.round_winner = alabel
            if not self.total_rounds:
                self.defending_team = 'B' if dealer_is_a else 'A'
            else:
                self._reset_round_state()
        elif rec.final_up_att > 0 or (sc <= 45 and sc >= 40):
            new_dealer = (self.dealer_pid + 1) % 4 if self.dealer_pid % 2 == 0 else (self.dealer_pid + 3) % 4
            self.dealer_pid = new_dealer
            self.defender_level, self.attacker_level = self.attacker_level, self.defender_level

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

        self._render_all()
        if not self.game_over_flag:
            self._after_id = self.root.after(self.step_delay * 2, self._step_next_round)

    def _reset_round_state(self):
        self.team_a_cumulative_steps = 0
        self.team_b_cumulative_steps = 0
        self.defending_team = None
        self.team_a_level = '7'
        self.team_b_level = '7'
        self.defender_level = '7'
        self.attacker_level = '7'

    def _finish_game(self):
        self.running = False
        self.btn_start.config(state=tk.NORMAL)
        self.btn_step.config(state=tk.DISABLED)
        self.btn_auto.config(state=tk.DISABLED)
        self._set_status(f"🏆 游戏结束 | 胜方: {self.winner or '—'}")
        self._render_all()

    # ==================== 渲染 ====================

    def _render_all(self):
        """完整渲染"""
        self.canvas.delete('all')
        w = self.canvas.winfo_width() or 1280
        h = self.canvas.winfo_height() or 830
        cx, cy = w // 2, h // 2

        # 评估阶段：展示手牌（从 self.hands）+ 底牌居中
        if self.engine_state in ('trump', 'bury', 'pick'):
            self._draw_pre_playing_hands(w, h, cx, cy)
            self._draw_bottom_cards(w, h, cx, cy)
            self._draw_stage_label(w, h, cx, cy)
        elif self.engine_state in ('playing', 'settled'):
            self._draw_player_hands(w, h, cx, cy)
            self._draw_center(w, h, cx, cy)

        if self.current_trick:
            self._draw_trick_result(w, h, cx, cy)

        if self.game_over_flag:
            self._draw_game_over(w, h)

    def _draw_pre_playing_hands(self, w, h, cx, cy):
        """发牌/定主阶段的四方手牌（面朝下或面朝上）"""
        small = True
        cw, ch = (52, 74) if small else (CARD_W, CARD_H)
        gap = 8

        for pid in range(4):
            hand = self.hands[pid] if self.hands else []
            if not hand:
                continue
            hand_sorted = sorted(hand, key=lambda c: cp(c, self.rec.level, self.rec.trump_suit or ''), reverse=True) \
                if self.rec.trump_suit else hand

            label = f"玩家{pid+1}"
            if pid == self.dealer_pid:
                label += " (庄)"
            elif pid not in self.rec.dealer_team:
                label += " (抓)"

            if pid == 0:
                for i, card in enumerate(hand_sorted):
                    draw_card(self.canvas, 10, 80 + i * (ch + gap), card, small=True)
                self.canvas.create_text(5, 65, text=label, fill=TEXT_LIGHT, font=('Microsoft YaHei', 10, 'bold'), anchor='w')
            elif pid == 1:
                for i, card in enumerate(hand_sorted):
                    draw_card(self.canvas, w - cw - 10, 80 + i * (ch + gap), card, small=True)
                self.canvas.create_text(w - 5, 65, text=label, fill=TEXT_LIGHT, font=('Microsoft YaHei', 10, 'bold'), anchor='e')
            elif pid == 2:
                start_x = cx - (len(hand_sorted) * (cw + gap)) // 2
                for i, card in enumerate(hand_sorted):
                    draw_card(self.canvas, start_x + i * (cw + gap), 60, card, small=True)
                self.canvas.create_text(cx, 45, text=label, fill=TEXT_LIGHT, font=('Microsoft YaHei', 10, 'bold'), anchor='center')
            elif pid == 3:
                start_x = cx - (len(hand_sorted) * (cw + gap)) // 2
                for i, card in enumerate(hand_sorted):
                    draw_card(self.canvas, start_x + i * (cw + gap), h - ch - 30, card, small=True)
                self.canvas.create_text(cx, h - ch - 45, text=label, fill=TEXT_LIGHT, font=('Microsoft YaHei', 10, 'bold'), anchor='center')

    def _draw_bottom_cards(self, w, h, cx, cy):
        """底牌居中展示"""
        if not self.bottom:
            return
        cw, ch, gap = 52, 74, 8
        start_x = cx - (len(self.bottom) * (cw + gap)) // 2
        y = cy - ch - 20
        self.canvas.create_text(cx, y - 20, text=f"🂠 底牌 ({len(self.bottom)}张)", fill='#f1c40f',
                               font=('Microsoft YaHei', 11, 'bold'), anchor='center')
        for i, card in enumerate(self.bottom):
            draw_card(self.canvas, start_x + i * (cw + gap), y, card, small=True)

    def _draw_stage_label(self, w, h, cx, cy):
        """阶段标签 — 放在桌面中央上方空旷区域"""
        labels = {
            'trump': '⭐ 定主阶段 — 亮牌 / 闷牌',
            'bury': '📦 埋底阶段 — 庄家选牌埋入底牌',
            'pick': '🔍 捡主阶段 — 翻开闷牌，拣出主牌',
        }
        text = labels.get(self.engine_state, '')
        if text:
            self.canvas.create_text(cx, cy - 165, text=text, fill='#f39c12',
                                   font=('Microsoft YaHei', 12, 'bold'), anchor='center')

    def _draw_player_hands(self, w, h, cx, cy):
        """绘制四方玩家的手牌（始终显示标签和牌数）"""
        small = True
        cw, ch = (52, 74) if small else (CARD_W, CARD_H)
        gap = 8
        dealer_pid = self.dealer_pid
        dt = self.dt

        for pid in range(4):
            side = '(庄)' if pid in dt else '(抓)'
            hand = sorted(self.bots[pid].hand, key=lambda c: cp(c, self.rec.level, self.rec.trump_suit or ''), reverse=True) \
                if pid in self.bots and self.bots[pid].hand else []
            label = f"玩家{pid+1}{side} ({len(hand)}张)"

            if pid == 0:
                if hand:
                    for i, card in enumerate(hand):
                        draw_card(self.canvas, 10, 80 + i * (ch + gap), card, small=True)
                else:
                    self.canvas.create_text(10 + cw // 2, 80 + ch // 2, text="—", fill='#7f8c8d',
                                           font=('Microsoft YaHei', 12), anchor='center')
                self.canvas.create_text(5, 65, text=label, fill=TEXT_LIGHT, font=('Microsoft YaHei', 10, 'bold'), anchor='w')
            elif pid == 1:
                if hand:
                    for i, card in enumerate(hand):
                        draw_card(self.canvas, w - cw - 10, 80 + i * (ch + gap), card, small=True)
                else:
                    self.canvas.create_text(w - 10 - cw // 2, 80 + ch // 2, text="—", fill='#7f8c8d',
                                           font=('Microsoft YaHei', 12), anchor='center')
                self.canvas.create_text(w - 5, 65, text=label, fill=TEXT_LIGHT, font=('Microsoft YaHei', 10, 'bold'), anchor='e')
            elif pid == 2:
                if hand:
                    start_x = cx - (len(hand) * (cw + gap)) // 2
                    for i, card in enumerate(hand):
                        draw_card(self.canvas, start_x + i * (cw + gap), 60, card, small=True)
                self.canvas.create_text(cx, 45, text=label, fill=TEXT_LIGHT, font=('Microsoft YaHei', 10, 'bold'), anchor='center')
            elif pid == 3:
                if hand:
                    start_x = cx - (len(hand) * (cw + gap)) // 2
                    for i, card in enumerate(hand):
                        draw_card(self.canvas, start_x + i * (cw + gap), h - ch - 30, card, small=True)
                self.canvas.create_text(cx, h - ch - 45, text=label, fill=TEXT_LIGHT, font=('Microsoft YaHei', 10, 'bold'), anchor='center')

    def _draw_center(self, w, h, cx, cy):
        """绘制中央出牌区和信息"""
        if self.current_trick:
            played = self.current_trick['played']
            positions = [
                (cx - CARD_W - 15, cy - 20),
                (cx + 15, cy - 20),
                (cx - CARD_W // 2, cy - CARD_H - 40),
                (cx - CARD_W // 2, cy + 10),
            ]
            for (pid, cl), (px, py) in zip(played, positions):
                if cl:
                    for j, card in enumerate(cl):
                        draw_card(self.canvas, px + j * (CARD_W + 4), py, card,
                                 highlight=(pid == self.current_trick.get('winner')))

        if self.rec:
            bottom = self.rec.bottom_after_bury or self.rec.initial_bottom
            bs = sum(SCORE_VALUES.get(c.rank, 0) for c in bottom)
            ts = self.rec.trump_suit or '—'
            self.canvas.create_text(cx, cy - 155, text=f"主: {SUIT_CN.get(ts, ts)} | 底牌: {bs}分",
                                   fill='#bdc3c7', font=('Microsoft YaHei', 9), anchor='center')

        if self.engine_state == 'settled' and self.rec:
            rec = self.rec
            settle_text = f"抓分: {rec.attacker_score}分 | 庄方+{rec.final_up_def} 抓方+{rec.final_up_att}"
            self.canvas.create_text(cx, cy + 100, text=settle_text, fill='#f1c40f',
                                   font=('Microsoft YaHei', 13, 'bold'), anchor='center')

        level_text = f"队伍A: {self.team_a_level}  |  队伍B: {self.team_b_level}"
        self.canvas.create_text(cx, cy - 135, text=level_text, fill=TEXT_LIGHT,
                               font=('Microsoft YaHei', 10), anchor='center')

    def _draw_trick_result(self, w, h, cx, cy):
        """当前圈结果"""
        if not self.current_trick:
            return
        t = self.current_trick
        pnames = {'single': '单张', '510k': '5·10·K', 'hong': '💥轰', 'zha': '💣炸'}
        pname = pnames.get(t['pattern'], '单张')
        text = f"第{t['num']}圈 [{pname}] 赢: 玩家{t['winner']+1} (+{t['score']}分)"
        self.canvas.create_text(cx, cy + 130, text=text, fill='#f39c12',
                               font=('Microsoft YaHei', 11, 'bold'), anchor='center')

    def _draw_game_over(self, w, h):
        self.canvas.create_rectangle(0, 0, w, h, fill='#00000060', outline='')
        self.canvas.create_text(w // 2, h // 2 - 20,
                               text=f"🏆 {self.winner or '游戏结束'}",
                               fill='#f1c40f', font=('Microsoft YaHei', 32, 'bold'))
        self.canvas.create_text(w // 2, h // 2 + 30,
                               text=f"共 {self.rnd} 局 | 队伍A:{self.team_a_level} 队伍B:{self.team_b_level}",
                               fill=TEXT_LIGHT, font=('Microsoft YaHei', 14))

    def _set_status(self, text):
        self.status_bar.config(text=text)

    # ==================== 定时器驱动 ====================

    def _tick(self):
        """定时器回调（仅自动模式使用）"""
        if not self.running or self.step_mode or self.game_over_flag:
            return

        if self.engine_state in ('trump', 'bury', 'pick'):
            self._do_one_step()
            self._after_id = self.root.after(self.step_delay, self._tick)
        elif self.engine_state == 'playing':
            self._play_next_trick()
            if self.engine_state == 'settled':
                self._after_id = self.root.after(self.step_delay * 3, self._tick)
            else:
                self._after_id = self.root.after(self.step_delay, self._tick)
        elif self.engine_state == 'settled':
            self._set_status(f"结算完成 | 庄家方={self.defender_level} 抓分方={self.attacker_level}")
            if not self.game_over_flag:
                self._step_next_round()
                self._after_id = self.root.after(self.step_delay * 2, self._tick)

    def run(self):
        self.root.mainloop()


# ==================== 主入口 ====================

if __name__ == '__main__':
    app = GameGUI()
    app.run()
