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

def _rounded_rect_points(x, y, w, h, r, n=8):
    """生成圆角矩形多边形点序列 — 完整追踪外轮廓（含4直边+4圆角）"""
    import math
    pts = []
    # 直边 + 圆角交替，逆时针追踪轮廓
    # 圆角公式: px = cx + r*cos(a), py = cy - r*sin(a)
    # 4个圆角依次从起始角递减 π/2（顺时针追踪外弧）

    # 上边: (x+r,y) → (x+w-r,y)
    pts.extend([x + r, y, x + w - r, y])
    # 右上圆角: 圆心(x+w-r, y+r), 角 π/2→0 (递减)
    for i in range(n):
        a = math.pi/2 - (math.pi/2) * i / (n - 1)
        pts.extend([x + w - r + r * math.cos(a), y + r - r * math.sin(a)])
    # 右边: (x+w, y+r) → (x+w, y+h-r)
    pts.extend([x + w, y + r, x + w, y + h - r])
    # 右下圆角: 圆心(x+w-r, y+h-r), 角 0→-π/2 (递减)
    for i in range(n):
        a = 0 - (math.pi/2) * i / (n - 1)
        pts.extend([x + w - r + r * math.cos(a), y + h - r - r * math.sin(a)])
    # 下边: (x+w-r, y+h) → (x+r, y+h)
    pts.extend([x + w - r, y + h, x + r, y + h])
    # 左下圆角: 圆心(x+r, y+h-r), 角 -π/2→-π (递减)
    for i in range(n):
        a = -math.pi/2 - (math.pi/2) * i / (n - 1)
        pts.extend([x + r + r * math.cos(a), y + h - r - r * math.sin(a)])
    # 左边: (x, y+h-r) → (x, y+r)
    pts.extend([x, y + h - r, x, y + r])
    # 左上圆角: 圆心(x+r, y+r), 角 -π→-3π/2 (递减)
    for i in range(n):
        a = -math.pi - (math.pi/2) * i / (n - 1)
        pts.extend([x + r + r * math.cos(a), y + r - r * math.sin(a)])

    return pts


def _trump_stars(card, level, trump_suit):
    """返回主牌星数：常驻主牌(大王/小王/♥3/2/级牌)=★★，本局主花色=★，非主牌=0"""
    if not level or not trump_suit:
        return 0
    if card.rank in ('大王', '小王'):
        return 2
    if card.rank == '3' and card.suit == '♥':
        return 2
    if card.rank == '2':
        return 2
    if card.rank == level:
        return 2
    if card.suit == trump_suit:
        return 1
    return 0


def draw_card(canvas, x, y, card, highlight=False, small=False, level=None, trump_suit=None):
    """在 Canvas 上绘制一张扑克牌"""
    w, h, r = (52, 74, 7) if small else (CARD_W, CARD_H, CARD_R)
    color = SUIT_COLORS.get(card.suit, SUIT_COLORS['王'])

    # 单张圆角矩形（白色填充 + 边框，无拼接）
    pts = _rounded_rect_points(x, y, w, h, r)
    canvas.create_polygon(pts, fill='white', outline='#bdc3c7' if not highlight else '#e74c3c',
                         width=2 if highlight else 1, tags='card')

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

    # 主牌标记：左下角 ★ / ★★（实心五角星）
    sc = _trump_stars(card, level, trump_suit)
    if sc:
        star_size = 8 if small else 10
        star_text = '★' * sc
        canvas.create_text(x + 6, y + h - 6, text=star_text, fill='#f1c40f',
                          font=('Microsoft YaHei', star_size), anchor='sw', tags='card')


def draw_compact_card(canvas, x, y, card, highlight=False, level=None, trump_suit=None):
    """缩小40%的迷你牌面 (31×44)"""
    w, h, r = 31, 44, 4
    color = SUIT_COLORS.get(card.suit, SUIT_COLORS['王'])

    # 单张圆角矩形（白色填充 + 边框）
    pts = _rounded_rect_points(x, y, w, h, r, n=6)
    canvas.create_polygon(pts, fill='white', outline='#bdc3c7' if not highlight else '#e74c3c',
                         width=2 if highlight else 1, tags='card')

    # 文字
    mcx, mcy = x + w // 2, y + h // 2
    if card.rank in ('大王', '小王'):
        jc = '#c0392b' if card.rank == '大王' else '#1a1a2e'
        canvas.create_text(mcx, mcy - 1, text='大' if card.rank == '大王' else '小',
                          fill=jc, font=('Microsoft YaHei', 10, 'bold'), tags='card')
    else:
        canvas.create_text(mcx, mcy, text=f"{card.rank}{card.suit}", fill=color,
                          font=('Segoe UI Symbol', 16), tags='card')

    # 主牌标记：左下角 ★ / ★★（实心五角星）
    sc = _trump_stars(card, level, trump_suit)
    if sc:
        canvas.create_text(x + 4, y + h - 4, text='★' * sc, fill='#f1c40f',
                          font=('Microsoft YaHei', 7), anchor='sw', tags='card')


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
        self._reveal_count = None
        self._pending_trick = None
        self.dealer_pid = 0
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

        self.btn_reset = tk.Button(top_frame, text="🔄 重置", command=self.reset_game,
                                    bg='#c0392b', fg='white', font=('Microsoft YaHei', 11),
                                    width=8, relief=tk.FLAT, cursor='hand2')
        self.btn_reset.pack(side=tk.LEFT, padx=5, pady=8)

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
        parts = val.replace('-', ':').split(':')
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

    def reset_game(self):
        """重置到初始状态，清空牌桌和所有记录"""
        # 停止自动模式定时器
        if self._after_id:
            self.root.after_cancel(self._after_id)
            self._after_id = None

        # 重置状态
        self.running = False
        self.step_mode = True
        self.game_over_flag = False
        self.winner = None
        self._reveal_count = None
        self._pending_trick = None

        # 局数据
        self.rec = None
        self.hands = None
        self.bottom = None
        self.bots = {}
        self.trick_idx = 0
        self.current_trick = None
        self.dt = []
        self.at = []

        # 引擎数据
        self.engine_state = None
        self.dealer_pid = 0
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

        # 按钮状态
        self.btn_start.config(state=tk.NORMAL)
        self.btn_step.config(state=tk.DISABLED)
        self.btn_auto.config(state=tk.DISABLED)
        self.btn_auto.config(text="▶▶ 自动", bg=BUTTON_BG, fg=TEXT_LIGHT)
        self.btn_export.config(state=tk.DISABLED)

        # 清空画布
        self.canvas.delete('all')
        self._set_status("就绪 | 点击「开始」启动游戏")

    # ==================== 游戏步骤引擎 ====================

    def _step_next_round(self):
        """开始新一局"""
        if self.game_over_flag:
            self._finish_game()
            return

        # 切换为下局等级
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

        self._set_status(f"第 {self.rnd} 局 | 庄家方={self.defender_level} 抓分方={self.attacker_level}")
        self.bots = {}
        self.trick_idx = 0
        self.current_trick = None
        self._deal()
        self.engine_state = 'trump'
        self._render_all()

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
                    rec.bottom_trump_card = fc

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
        """播放下一圈 — 支持逐玩家揭示动画"""
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

        # 任一玩家手牌为空则立即结算（防止出牌数量不一致）
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

        # 手牌已空则直接结算，不做动画
        if any(len(bots[p].hand) == 0 for p in range(4)):
            self.current_trick = trick
            self.trick_leader = best_pid
            self._settle_and_continue()
            return

        # 启动逐张揭示动画
        self._pending_trick = trick
        self._reveal_count = 0
        self._reveal_next_card()

    def _reveal_next_card(self):
        """逐玩家揭示出牌（每调用一次多展示一个玩家的牌）"""
        self._reveal_count += 1
        trick = self._pending_trick

        # 设置已揭示的牌
        revealed = trick['played'][:self._reveal_count]
        self.current_trick = {**trick, 'played': revealed}
        self._render_all()

        if self._reveal_count >= 4:
            # 全部揭示完成
            self._reveal_count = None
            self._pending_trick = None
            self.trick_leader = trick['winner']

            # 若任一方手牌为空则立即结算
            if any(len(self.bots[p].hand) == 0 for p in range(4)):
                self._settle_and_continue()
                return

            self._set_status(f"第 {self.rnd} 局 | 第 {trick['num']} 圈 | 赢家: 玩家{trick['winner']+1} (+{trick['score']}分)")

            # 自动模式：动画结束后继续调度 _tick
            if not self.step_mode:
                self._after_id = self.root.after(self.step_delay, self._tick)
            return

        # 自动模式：延时推进下一张
        if not self.step_mode:
            self._after_id = self.root.after(self.step_delay // 3, self._reveal_next_card)

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

        # 计算本局升级后的等级（暂不更新 defender_level/attacker_level，延迟到下一局开始时切换）
        new_def = level_up(self.defender_level, rec.final_up_def)
        new_att = level_up(self.attacker_level, rec.final_up_att)

        # 锁存显示用下局等级（避免过7重置覆盖）
        if rec.final_up_att > 0 or (sc <= 45 and sc >= 40):
            self._next_defender_level = new_att  # 闲家上台
            self._next_attacker_level = new_def  # 庄家变闲家（保持升级后等级）
        else:
            self._next_defender_level = new_def  # 庄家留守
            self._next_attacker_level = new_att  # 闲家不变

        # 过7判定：用累计升档数（>=13 即完成一轮完整循环）
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
        elif rec.final_up_att > 0 or (sc <= 45 and sc >= 40):
            new_dealer = (self.dealer_pid + 1) % 4 if self.dealer_pid % 2 == 0 else (self.dealer_pid + 3) % 4
            self.dealer_pid = new_dealer
            # 闲家上台：交换攻守，等级相应交换
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

        self._render_all()
        if not self.game_over_flag:
            if not self.step_mode:
                self._after_id = self.root.after(self.step_delay * 2, self._tick)
            # 步进模式：不做自动调度，等待用户点击下一步

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

    def _finish_game(self):
        self.running = False
        self._reveal_count = None
        self._pending_trick = None
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

        # 右上角信息：主牌 + 当前等级
        if self.rec and self.rec.trump_suit:
            ts = SUIT_CN.get(self.rec.trump_suit, self.rec.trump_suit)
            self.canvas.create_text(w - 180, 14, text=f"主: {ts}", fill='#bdc3c7',
                                   font=('Microsoft YaHei', 9), anchor='w')
        level_text = f"本局打 {self.defender_level}"
        self.canvas.create_text(w - 180, 34, text=level_text, fill='#f1c40f',
                               font=('Microsoft YaHei', 12, 'bold'), anchor='w')

        # 评估阶段：展示手牌（从 self.hands）+ 底牌居中
        if self.engine_state in ('trump', 'bury', 'pick'):
            self._draw_pre_playing_hands(w, h, cx, cy)
            self._draw_bottom_cards(w, h, cx, cy)
            self._draw_stage_label(w, h, cx, cy)
            self._draw_trump_indicators(w, h, cx, cy)
        elif self.engine_state in ('playing', 'settled'):
            self._draw_player_hands(w, h, cx, cy)
            self._draw_buried_bottom_compact(w, h, cx)
            self._draw_center(w, h, cx, cy)

        if self.current_trick and self._reveal_count is None and self.engine_state != 'settled':
            self._draw_trick_result(w, h, cx, cy)

        if self.game_over_flag:
            self._draw_game_over(w, h)

    def _draw_pre_playing_hands(self, w, h, cx, cy):
        """发牌/定主阶段的四方手牌 — 0=下方 1=右方 2=上方 3=左方（紧凑尺寸）"""
        cw, ch, gap = 31, 44, 5  # 约缩小40%

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
                start_x = cx - (len(hand_sorted) * (cw + gap)) // 2
                y = h - ch - 15
                for i, card in enumerate(hand_sorted):
                    draw_compact_card(self.canvas, start_x + i * (cw + gap), y, card,
                                     level=self.rec.level, trump_suit=self.rec.trump_suit)
                self.canvas.create_text(cx, y - 5, text=label, fill=TEXT_LIGHT,
                                       font=('Microsoft YaHei', 10, 'bold'), anchor='center')
            elif pid == 1:
                x = w - cw - 6; y0 = 60
                for i, card in enumerate(hand_sorted):
                    draw_compact_card(self.canvas, x, y0 + i * (ch + gap), card,
                                     level=self.rec.level, trump_suit=self.rec.trump_suit)
                self.canvas.create_text(w - 4, 50, text=label, fill=TEXT_LIGHT,
                                       font=('Microsoft YaHei', 10, 'bold'), anchor='e')
            elif pid == 2:
                start_x = cx - (len(hand_sorted) * (cw + gap)) // 2
                y = 12
                for i, card in enumerate(hand_sorted):
                    draw_compact_card(self.canvas, start_x + i * (cw + gap), y, card,
                                     level=self.rec.level, trump_suit=self.rec.trump_suit)
                self.canvas.create_text(cx, 8, text=label, fill=TEXT_LIGHT,
                                       font=('Microsoft YaHei', 10, 'bold'), anchor='center')
            elif pid == 3:
                x = 6; y0 = 60
                for i, card in enumerate(hand_sorted):
                    draw_compact_card(self.canvas, x, y0 + i * (ch + gap), card,
                                     level=self.rec.level, trump_suit=self.rec.trump_suit)
                self.canvas.create_text(4, 50, text=label, fill=TEXT_LIGHT,
                                       font=('Microsoft YaHei', 10, 'bold'), anchor='w')

    def _draw_bottom_cards(self, w, h, cx, cy):
        """底牌居中展示"""
        if not self.bottom:
            return
        cw, ch, gap = 52, 74, 8
        start_x = cx - (len(self.bottom) * (cw + gap)) // 2
        y = cy - ch - 20
        title = "🂠 底牌"
        if self.rec and self.rec.trump_method == 'bottom_card':
            title += " (翻底牌定主)"
        self.canvas.create_text(cx, y - 20, text=f"{title} ({len(self.bottom)}张)", fill='#f1c40f',
                               font=('Microsoft YaHei', 11, 'bold'), anchor='center')
        for i, card in enumerate(self.bottom):
            is_trump_card = (self.rec and self.rec.trump_method == 'bottom_card'
                            and self.rec.bottom_trump_card
                            and card.rank == self.rec.bottom_trump_card.rank
                            and card.suit == self.rec.bottom_trump_card.suit)
            draw_card(self.canvas, start_x + i * (cw + gap), y, card, small=True,
                     highlight=is_trump_card,
                     level=self.rec.level, trump_suit=self.rec.trump_suit)
            if is_trump_card:
                self.canvas.create_text(start_x + i * (cw + gap) + cw // 2, y + ch + 15,
                                       text='🔴 亮底牌', fill='#e74c3c',
                                       font=('Microsoft YaHei', 8, 'bold'), anchor='center')

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

    def _draw_trump_indicators(self, w, h, cx, cy):
        """在定主阶段，于对应玩家手牌与桌面中央之间展示亮牌/闷牌"""
        rec = self.rec
        if not rec:
            return

        # 4个玩家的指示器位置（手牌与中央之间）— 0=下 1=右 2=上 3=左
        indicator_pos = {
            0: (cx, h - 160),      # 下方玩家：手牌上方
            1: (w - 80, cy),       # 右方玩家：手牌左侧
            2: (cx, 145),          # 上方玩家：手牌下方
            3: (80, cy),           # 左方玩家：手牌右侧
        }

        if rec.trump_method == 'bright' and rec.bright_pid is not None:
            px, py = indicator_pos[rec.bright_pid]
            self.canvas.create_text(px, py - 40, text='⭐ 亮牌', fill='#f1c40f',
                                   font=('Microsoft YaHei', 11, 'bold'), anchor='center')
            draw_card(self.canvas, px - CARD_W // 2, py - 10, rec.bright_card, highlight=True,
                     level=rec.level, trump_suit=rec.trump_suit)

        elif rec.trump_method == 'concealed' and rec.concealed_pid is not None:
            px, py = indicator_pos[rec.concealed_pid]
            self.canvas.create_text(px, py - 40, text='🃏 闷牌', fill='#3498db',
                                   font=('Microsoft YaHei', 11, 'bold'), anchor='center')
            draw_card(self.canvas, px - CARD_W // 2, py - 10, rec.concealed_card, highlight=True,
                     level=rec.level, trump_suit=rec.trump_suit)

    def _draw_buried_bottom_compact(self, w, h, cx):
        """埋底后的底牌组 — 缩小40%置于屏幕正下方，不遮挡下手牌"""
        if not self.rec or not self.rec.bottom_after_bury:
            return
        rec = self.rec
        bottom = rec.bottom_after_pick or rec.bottom_after_bury
        cw, ch, gap = 31, 44, 5
        y = h - 215

        # 组装标题：埋底 + 捡主信息
        label_parts = [f"📦 玩家{self.dealer_pid+1}埋底"]
        if rec.concealed_pid is not None and rec.picked_from_bottom:
            picked_str = ', '.join(c.rank if c.rank in ('大王', '小王') else f"{c.rank}{c.suit}"
                                    for c in rec.picked_from_bottom)
            label_parts.append(f"🔍 玩家{rec.concealed_pid+1}捡主 ({picked_str})")
        dealer_label = ' | '.join(label_parts) + f" ({len(bottom)}张)"
        self.canvas.create_text(cx, y - 12, text=dealer_label, fill='#f1c40f',
                               font=('Microsoft YaHei', 10, 'bold'), anchor='center')
        start_x = cx - (len(bottom) * (cw + gap)) // 2
        for i, card in enumerate(bottom):
            draw_compact_card(self.canvas, start_x + i * (cw + gap), y, card,
                            level=rec.level, trump_suit=rec.trump_suit)

        # 底分总数（底牌下方）
        bs = sum(SCORE_VALUES.get(c.rank, 0) for c in bottom)
        self.canvas.create_text(cx, y + ch + 12, text=f"底牌: {bs}分", fill='#bdc3c7',
                               font=('Microsoft YaHei', 8), anchor='center')

    def _draw_player_hands(self, w, h, cx, cy):
        """绘制四方玩家的手牌 — 0=下方 1=右方 2=上方 3=左方（紧凑尺寸）"""
        cw, ch, gap = 31, 44, 5  # 约缩小40%
        dealer_pid = self.dealer_pid
        dt = self.dt

        for pid in range(4):
            side = '(庄)' if pid in dt else '(抓)'
            hand = sorted(self.bots[pid].hand, key=lambda c: cp(c, self.rec.level, self.rec.trump_suit or ''), reverse=True) \
                if pid in self.bots and self.bots[pid].hand else []
            label = f"玩家{pid+1}{side} ({len(hand)}张)"

            if pid == 0:
                y = h - ch - 15
                if hand:
                    start_x = cx - (len(hand) * (cw + gap)) // 2
                    for i, card in enumerate(hand):
                        draw_compact_card(self.canvas, start_x + i * (cw + gap), y, card,
                                         level=self.rec.level, trump_suit=self.rec.trump_suit)
                self.canvas.create_text(cx, y - 5, text=label, fill=TEXT_LIGHT,
                                       font=('Microsoft YaHei', 10, 'bold'), anchor='center')
            elif pid == 1:
                x = w - cw - 6; y0 = 60
                if hand:
                    for i, card in enumerate(hand):
                        draw_compact_card(self.canvas, x, y0 + i * (ch + gap), card,
                                         level=self.rec.level, trump_suit=self.rec.trump_suit)
                else:
                    self.canvas.create_text(x + cw // 2, y0 + ch // 2, text="—", fill='#7f8c8d',
                                           font=('Microsoft YaHei', 12), anchor='center')
                self.canvas.create_text(w - 4, 50, text=label, fill=TEXT_LIGHT,
                                       font=('Microsoft YaHei', 10, 'bold'), anchor='e')
            elif pid == 2:
                y = 12
                if hand:
                    start_x = cx - (len(hand) * (cw + gap)) // 2
                    for i, card in enumerate(hand):
                        draw_compact_card(self.canvas, start_x + i * (cw + gap), y, card,
                                         level=self.rec.level, trump_suit=self.rec.trump_suit)
                self.canvas.create_text(cx, 8, text=label, fill=TEXT_LIGHT,
                                       font=('Microsoft YaHei', 10, 'bold'), anchor='center')
            elif pid == 3:
                x = 6; y0 = 60
                if hand:
                    for i, card in enumerate(hand):
                        draw_compact_card(self.canvas, x, y0 + i * (ch + gap), card,
                                         level=self.rec.level, trump_suit=self.rec.trump_suit)
                else:
                    self.canvas.create_text(x + cw // 2, y0 + ch // 2, text="—", fill='#7f8c8d',
                                           font=('Microsoft YaHei', 12), anchor='center')
                self.canvas.create_text(4, 50, text=label, fill=TEXT_LIGHT,
                                       font=('Microsoft YaHei', 10, 'bold'), anchor='w')

    def _draw_center(self, w, h, cx, cy):
        """绘制中央出牌区和信息"""
        if self.current_trick:
            played = self.current_trick['played']
            # 红框 & 牌型名称仅在4人全出完时显示
            all_revealed = self._reveal_count is None
            # 4个玩家出牌位置：按 pid 映射，各偏向所属玩家一侧
            pid_positions = {
                0: (cx - CARD_W // 2, 480),        # pid=0 下方玩家
                1: (880, cy - CARD_H // 2),        # pid=1 右侧玩家
                2: (cx - CARD_W // 2, 200),        # pid=2 上方玩家
                3: (280, cy - CARD_H // 2),        # pid=3 左侧玩家
            }
            for pid, cl in played:
                if not cl:
                    continue
                px, py = pid_positions[pid]
                total_w = len(cl) * (CARD_W + 4) - 4
                start_x = px + (CARD_W - total_w) // 2
                for j, card in enumerate(cl):
                    is_winner = all_revealed and (pid == self.current_trick.get('winner'))
                    draw_card(self.canvas, start_x + j * (CARD_W + 4), py, card,
                             highlight=is_winner,
                             level=self.rec.level, trump_suit=self.rec.trump_suit)

                # 特殊牌型名称（仅全部揭示后显示）
                if all_revealed and len(cl) > 1:
                    pname = self._trick_pattern_name(cl)
                    if pname:
                        mid_x = start_x + total_w // 2
                        self.canvas.create_text(mid_x, py + CARD_H + 12, text=pname,
                                               fill='#f39c12', font=('Microsoft YaHei', 9, 'bold'),
                                               anchor='center')

        if self.engine_state == 'settled' and self.rec:
            self._draw_settlement(w, h, cx, cy)

    @staticmethod
    def _trick_pattern_name(cl):
        """检测牌型名称：轰|炸|510K|单张(空)"""
        if len(cl) == 1:
            return None
        if len(cl) == 3 and {c.rank for c in cl} == {'5', '10', 'K'}:
            return '510K'
        if len(cl) == 4:
            ranks = [c.rank for c in cl]
            if len(set(ranks)) == 1:
                return '💥 轰'
            if len(set(ranks)) == 2 and 'A' in ranks:
                return '💣 炸'
        return None

    def _draw_settlement(self, w, h, cx, cy):
        """本局结算：扣底 + 升级 + 下局等级，居中显示"""
        rec = self.rec
        lines = []
        y0 = cy - 50

        # 1. 扣底信息
        is_bottom = rec.last_trick_winner_side == 'attacker'
        if is_bottom:
            lp_pid = rec.last_trick_winner_pid
            lines.append(f"玩家{lp_pid+1} 扣底 | 得分：{rec.attacker_score}")
        else:
            lines.append(f"得分：{rec.attacker_score}")

        # 2. 升级信息
        if rec.final_up_def > 0 or rec.final_up_att > 0:
            parts = []
            if rec.final_up_def > 0:
                parts.append(f"庄家 +{rec.final_up_def}级")
            if rec.final_up_att > 0:
                parts.append(f"闲家 +{rec.final_up_att}级")
            lines.append(' | '.join(parts))

        # 3. 下局等级
        lines.append(f"下局打 {self._next_defender_level}")

        for i, text in enumerate(lines):
            fs = 13 if i == 0 else 11
            color = '#f1c40f' if i == 0 else '#f39c12'
            self.canvas.create_text(cx, y0 + i * 30, text=text, fill=color,
                                   font=('Microsoft YaHei', fs, 'bold'), anchor='center')

    def _draw_trick_result(self, w, h, cx, cy):
        """当前圈结果"""
        if not self.current_trick:
            return
        t = self.current_trick
        pnames = {'single': '单张', '510k': '5·10·K', 'hong': '💥轰', 'zha': '💣炸'}
        pname = pnames.get(t['pattern'], '单张')
        text = f"第{t['num']}圈 [{pname}] 赢: 玩家{t['winner']+1} (+{t['score']}分)"
        self.canvas.create_text(cx, cy, text=text, fill='#f39c12',
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
            if self._reveal_count is not None:
                return  # 动画进行中，由 _reveal_next_card 的 after 继续调度
            if self.engine_state == 'settled':
                return  # _settle_and_continue 已调度 _tick
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
