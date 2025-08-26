import asyncio
import display
import gc
import math

from sys import implementation as _sys_implementation
if _sys_implementation.name != "micropython":
    from typing import Callable, List, Tuple, Union
    ChoiceTree = Tuple[str, List[Tuple[str, Union['ChoiceTree', Callable]]]]
from system.eventbus import eventbus
from events.input import ButtonDownEvent, BUTTON_TYPES
from app import App, SASPPUApp

from ..util.misc import *

import sasppu

BOX_WIDTH = 64 # half of width
BOX_HEIGHT = 120 # half of height
ITEM_WIDTH = 128
TITLE_WIDTH = 128

STATE_CLOSED = 0
STATE_CLOSING = 1
STATE_OPEN = 2
STATE_OPENING = 3

BASE_BG1_X = -(120-BOX_WIDTH) + 8
BASE_BG1_Y = -(120-BOX_HEIGHT) - 40

LINE_HEIGHT = 20
RESERVED_HEIGHT = LINE_HEIGHT*4
RESERVED_START = sasppu.Background.HEIGHT - RESERVED_HEIGHT

TITLE_START_X = 0
TITLE_START_Y = RESERVED_START
SUBTITLE_START_X = 128
SUBTITLE_START_Y = RESERVED_START

SPARE_TILE_X = sasppu.Background.WIDTH - 8
SPARE_TILE_Y = sasppu.Background.HEIGHT - 8

#----------------
#TTTTTTT_44444444
#1111111155555555
#2222222266666666
#3333333377777777

#----------------
#TTTTTTTTTTTTTTTT
#SSSSSSSSSSSSSSSS
#ACEGIKMOQSUWY___
#BDFHJLNPRTVXZ___

class ChoiceDialog:
    def _calc_sizes(self, ctx):
        self._sizes = [shrink_until_fit(ctx, choice[0], 150, 30) for choice in self._current_tree[1]]
    
    def _get_pos(self, index):
        return sum(self._sizes[0:index])
            
    def __init__(self, app: App, choices: ChoiceTree=("",[]), no_exit = False):
        self._tree = choices
        self._app = app
        self._open = False
        self._state = STATE_CLOSED
        
        self._previous_trees = []
        self._current_tree = self._tree
        self._selected = 0
        self._selected_visually = 0
        self._opened_amount = 0.0
        self._no_exit = no_exit
        self._sizes = []
        self.opened_event = asyncio.Event()
        self.closed_event = asyncio.Event()
        self.closed_event.set()
        
        self._text_update_needed = False

        self._sasppu_init()

    def _sasppu_init(self):
        self.ms = sasppu.MainState()
        self.ms.bind(False)
        self.cs = sasppu.CMathState()
        self.cs.bind(False)
        self.bg = sasppu.Background()
        self.bg.bind(1, False)
        self.bg1 = sasppu.bg1

        self.bg.windows = sasppu.WINDOW_ALL
        self.bg.x = BASE_BG1_X
        self.bg.y = BASE_BG1_Y
        self.bg.flags = 0

        self.ms.flags = sasppu.MainState.BG1_ENABLE 

        #self.ms.flags = sasppu.MainState.BG1_ENABLE | sasppu.MainState.CMATH_ENABLE
        #self.cs.flags = sasppu.CMathState.CMATH_ENABLE | sasppu.CMathState.SUB_SUB_SCREEN

        self._write_bg1_map()

        #self._fill_hdma()

    def _fill_hdma(self):
        for i in range(240):
            sasppu.hdma_7[i] = (sasppu.HDMA_NOOP, 0)
        sasppu.hdma_enable |= 0x80
        
        height = int(self._opened_amount * BOX_HEIGHT)
        box_top = 120 - height
        box_end = 120 + height

        ms_flags = self.ms.flags & (~sasppu.MainState.BG1_ENABLE) & 0xFF
        ms_sub_col = sasppu.grey555(13)
        cs_flags = self.cs.flags & (~sasppu.CMathState.CMATH_ENABLE) & 0xFF

        sasppu.hdma_7[0] = (sasppu.HDMA_MAIN_STATE_FLAGS, ms_flags)
        sasppu.hdma_7[1] = (sasppu.HDMA_CMATH_STATE_FLAGS, cs_flags)
        sasppu.hdma_7[2] = (sasppu.HDMA_MAIN_STATE_SUBSCREEN_COLOUR, ms_sub_col)

        sasppu.hdma_7[box_end] = (sasppu.HDMA_MAIN_STATE_FLAGS, ms_flags)
        sasppu.hdma_7[box_end + 3] = (sasppu.HDMA_MAIN_STATE_SUBSCREEN_COLOUR, ms_sub_col)
        sasppu.hdma_7[box_end + 5] = (sasppu.HDMA_CMATH_STATE_FLAGS, cs_flags)

        ms_flags |= sasppu.MainState.BG1_ENABLE
        ms_sub_col = sasppu.grey555(10)
        cs_flags |= sasppu.CMathState.CMATH_ENABLE

        sasppu.hdma_7[box_top - 5] = (sasppu.HDMA_CMATH_STATE_FLAGS, cs_flags)
        sasppu.hdma_7[box_top - 3] = (sasppu.HDMA_MAIN_STATE_SUBSCREEN_COLOUR, ms_sub_col)
        if box_top != box_end:
            sasppu.hdma_7[box_top] = (sasppu.HDMA_MAIN_STATE_FLAGS, ms_flags)

    def _clear_hdma(self):
        for i in range(240):
            sasppu.hdma_7[i] = (sasppu.HDMA_NOOP, 0)
        #sasppu.hdma_enable &= 0x7F
        #self.ms.flags &= (~sasppu.MainState.BG1_ENABLE) & 0xFF
        #self.cs.flags &= (~sasppu.CMathState.CMATH_ENABLE) & 0xFF

    def _write_bg1_map(self):
        for y in range(RESERVED_HEIGHT // 4):
            for x in range(sasppu.MAP_WIDTH):
                xend = ITEM_WIDTH // 8
                yend = RESERVED_HEIGHT // 8
                index = x + (y * sasppu.MAP_WIDTH)
                if x >= xend:
                    self.bg1[index] = (((SPARE_TILE_X) + ((SPARE_TILE_Y) * sasppu.Background.WIDTH)) // 8) * 4
                elif y >= yend:
                    self.bg1[index] = ((((x + xend) * 8) + ((((y - yend) * 8) + RESERVED_START) * sasppu.Background.WIDTH)) // 8) * 4
                else:
                    self.bg1[index] = (((x * 8) + (((y * 8) + RESERVED_START) * sasppu.Background.WIDTH)) // 8) * 4

    def is_open(self):
        return self._open
    
    def open(self):
        if not self.is_open():
            self._open = True
    
    def close(self):
        if self.is_open():
            self._cleanup()

    async def open_and_wait(self):
        await self.closed_event.wait()
        self._open = True
        await self.opened_event.wait()
    
    async def close_and_wait(self):
        await self.opened_event.wait()
        self._cleanup()
        await self.closed_event.wait()

    def set_choices(self, choices: ChoiceTree=(None, []), no_exit = False):
        self._tree = choices
        if self._state != STATE_CLOSED:
            self._previous_trees = []
            self._current_tree = self._tree
            self._selected = 0
            self._selected_visually = 0
        self._no_exit = no_exit
        self._text_update_needed = True
        if no_exit:
            self.open()
    
    def _draw_text(self):
        sasppu.fill_background(0, RESERVED_START, 256, RESERVED_HEIGHT, sasppu.TRANSPARENT_BLACK)
        width = sasppu.get_text_size(255, self._current_tree[0], True)[0]
        offset_left = (ITEM_WIDTH - width) // 2
        sasppu.draw_text_background(offset_left, RESERVED_START - 12, sasppu.WHITE, ITEM_WIDTH, self._current_tree[0], True)
        start_index = max(min(int(self._selected) - 3, len(self._current_tree[1]) - 7), 0)
        for (i, choice) in enumerate(self._current_tree[1][start_index : start_index + 7]):
            line = choice[0]
            if line == "":
                continue
            width = sasppu.get_text_size(255, line, True)[0]
            offset_left = (ITEM_WIDTH - width) // 2
            start_y = (i * LINE_HEIGHT) + LINE_HEIGHT
            if i >= 3:
                offset_left += ITEM_WIDTH
                start_y = ((i - 3) * LINE_HEIGHT)
            if int(self._selected) == start_index + i:
                colour = sasppu.rgb555(30,15,5)
            else:
                colour = sasppu.WHITE
            sasppu.draw_text_background(offset_left, RESERVED_START + (start_y) - 12, colour, width, line, True)
        sasppu.fill_background(SPARE_TILE_X, SPARE_TILE_Y, 8, 8, sasppu.GREEN)

    def update(self, delta: float):
        if self.is_open():
            if self._state == STATE_CLOSED:
                self._previous_trees = []
                self._current_tree = self._tree
                self._selected = 0
                self._selected_visually = 0
                self._state = STATE_OPENING
                self.closed_event.clear()
                self.opened_event.clear()
                self._opened_amount = 0.0
                eventbus.on(ButtonDownEvent, self._handle_buttondown, self._app)
            if self._state == STATE_OPENING:
                if self._opened_amount > 0.99:
                    self._opened_amount = 1.0
                    self._state = STATE_OPEN
                    self.opened_event.set()
                    return
                weight = math.pow(0.8, (delta/10))
                self._opened_amount = (self._opened_amount * (weight)) + (1-weight)
            elif self._state == STATE_CLOSING:
                if self._opened_amount < 0.01:
                    self._opened_amount = 0.0
                    self._state = STATE_CLOSED
                    self._open = False
                    self._clear_hdma()
                    self.closed_event.set()
                    return
                weight = math.pow(0.8, (delta/10))
                self._opened_amount = self._opened_amount * weight
            if self._sizes:
                ypos = self._get_pos(self._selected)
                if self._selected_visually != ypos:
                    weight = math.pow(0.8, (delta/10))
                    self._selected_visually = (self._selected_visually * (weight)) + (ypos * (1-weight))

    def _draw_focus_plane(self, ctx: Context, width: float):
        ctx.rgba(0.3, 0.3, 0.3, 0.8).rectangle((-80)*width, -120, (160)*width, 240).fill()
        col = ctx.rgba(0.2, 0.2, 0.2, 0.8)
        col.move_to((-80)*width,-120).line_to((-80)*width,120).stroke()
        col.move_to((80)*width,-120).line_to((80)*width,120).stroke()
    def _draw_header_plane(self, ctx: Context, width: float):
        ctx.rgba(0.1, 0.1, 0.1, 0.5).rectangle((-80)*width, -100, (160)*width, 40).fill()

    #def _draw_text(self, ctx: Context, choice: str, ypos: int, select: bool, header: bool=False):        
    #    if select:
    #        col = ctx.rgb(1.0,0.3,0.0)
    #    elif header:
    #        col = ctx.rgb(1.0,0.9,0.9)
    #    else:
    #        col = ctx.gray(0.8)
    #    col.move_to(0, ypos)\
    #        .text(choice)

    def draw(self):
        if self.is_open():
            if self._text_update_needed:
                self._text_update_needed = False
                self._draw_text()
            if self._state == STATE_OPENING or self._state == STATE_CLOSING:
                pass
                #self._fill_hdma()
            if self._selected_visually != self._selected:
                pass
                #self._set_bg1_scroll()
            #ctx.save()
            #ctx.text_baseline = Context.MIDDLE
            #ctx.text_align = Context.CENTER
            #self._draw_focus_plane(ctx, self._opened_amount)
            #current_header = self._current_tree[0]
            #if current_header != "":
            #    ctx.rectangle((-80)*self._opened_amount, -120, (160)*self._opened_amount, 240).clip()
            #    self._draw_header_plane(ctx, self._opened_amount)
            #    shrink_until_fit(ctx, current_header, 150, 30)
            #    self._draw_text(ctx, current_header, -80, False, header=True)
            #ctx.rectangle((-80)*self._opened_amount, -60, (160)*self._opened_amount, 180).clip()
            #self._calc_sizes(ctx)
            #for i, choice in enumerate(self._current_tree[1]):
            #    ctx.font_size = self._sizes[i]
            #    ypos = self._get_pos(i)-self._selected_visually
            #    if ypos < -80:
            #        continue
            #    if ypos > 120:
            #        break
            #    self._draw_text(ctx, choice[0], ypos, self._selected == i)
            #ctx.restore()

    def _handle_buttondown(self, event: ButtonDownEvent):
        if self.is_open():
            if BUTTON_TYPES["UP"] in event.button:
                self._selected = (self._selected - 1 + len(self._current_tree[1])) % len(self._current_tree[1])
            if BUTTON_TYPES["DOWN"] in event.button:
                self._selected = (self._selected + 1 + len(self._current_tree[1])) % len(self._current_tree[1])
            if BUTTON_TYPES["CONFIRM"] in event.button or BUTTON_TYPES["RIGHT"] in event.button:
                c = self._current_tree[1][self._selected][1]
                if callable(c):
                    c(self._app)
                    self._cleanup()
                    return
                self._previous_trees.append(self._current_tree)
                self._current_tree = c
                self._selected = 0
            if BUTTON_TYPES["CANCEL"] in event.button or BUTTON_TYPES["LEFT"] in event.button:
                if self._previous_trees:
                    self._current_tree = self._previous_trees.pop()
                    self._selected = 0
                elif not self._no_exit:
                    self._cleanup()
                    return
            self._text_update_needed = True

    def _cleanup(self):
        eventbus.remove(ButtonDownEvent, self._handle_buttondown, self._app)
        self._state = STATE_CLOSING
        self.closed_event.clear()
        self.opened_event.clear()

class ChoiceExample(SASPPUApp):
    def __init__(self):
        super().__init__()
        self.request_fast_updates = True
        
        sasppu.gfx_reset()
        self.ms = sasppu.MainState()
        self.ms.bind()
        self.cs = sasppu.CMathState()
        self.cs.bind()
        self.bg0 = sasppu.Background()
        self.bg0.bind(0)

        self.ms.mainscreen_colour = sasppu.grey555_cmath(20)
        sasppu.fill_background(0, 0, 256, 512, sasppu.BLUE)
        sasppu.fill_background(0, RESERVED_START, 256, RESERVED_HEIGHT, sasppu.RED)
        sasppu.fill_background(SPARE_TILE_X, SPARE_TILE_Y, 8, 8, sasppu.GREEN)

        self._choice = ChoiceDialog(
            app=self,
            choices=("Choice Test",[("thing 1", lambda a: a._set_answer("1")),
                     ("thing 2", lambda a: a._set_answer("2")),
                     ("thing 3", lambda a: a._set_answer("3")),
                     ("thing 4", lambda a: a._set_answer("4")),
                     ("thing 5", lambda a: a._set_answer("5")),
                     ("thing 6", lambda a: a._set_answer("6")),
                     ("moregyI", ("More Opts..", [("thing 41", lambda a: a._set_answer("41")),
                               ("thing 42", lambda a: a._set_answer("42"))]))])
        )
        self._answer = ""
        eventbus.on(ButtonDownEvent, self._handle_buttondown, self)
        self._choice.open()

    def _handle_buttondown(self, event: ButtonDownEvent):
        self._choice.open()

    def _set_answer(self, str: str):
        self._answer = str
        print(f"ANSWER: {self._answer}")

    def update(self, delta: float):
        self._choice.update(delta)

    async def background_task(self):
        while True:
            await asyncio.sleep(1)
            print("fps:", display.get_fps(), f"mem used: {gc.mem_alloc()}, mem free:{gc.mem_free()}")

    def draw(self):
        pass
        self._choice.draw()
