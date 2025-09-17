import asyncio
import math
import display
import gc

from system.eventbus import eventbus
from events.input import ButtonDownEvent
from app import App, SASPPUApp

import sasppu

MAX_LINE_WIDTH = 200
BOX_WIDTH = 100 # half of width
BOX_HEIGHT = 30 # half of height

STATE_CLOSED = 0
STATE_CLOSING = 1
STATE_OPEN = 2
STATE_OPENING = 3

BASE_BG1_X = -(120-BOX_WIDTH) + 8
BASE_BG1_Y = -(120-BOX_HEIGHT) - 1

LINE_HEIGHT = 20
RESERVED_HEIGHT = LINE_HEIGHT*4
RESERVED_START = sasppu.Background.HEIGHT - RESERVED_HEIGHT

class SpeechDialog:
    def __init__(self, app: App, speech: str):
        self._app = app
        self._open = False
        self._state = STATE_CLOSED
        self._opened_amount = 0.0
        self._ready_event = asyncio.Event()
        self._ready_event.set()
        self._stay_open = False
        self._text_update_needed = False

        self.set_speech(speech)
        self._sasppu_init()
        self.open()

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

        self.ms.flags = sasppu.MainState.BG1_ENABLE | sasppu.MainState.CMATH_ENABLE
        self.cs.flags = sasppu.CMathState.CMATH_ENABLE | sasppu.CMathState.SUB_SUB_SCREEN

        self._write_bg1_map()

        self._fill_hdma()

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

        self._set_bg1_scroll()

    def _clear_hdma(self):
        for i in range(240):
            sasppu.hdma_7[i] = (sasppu.HDMA_NOOP, 0)
        sasppu.hdma_enable &= 0x7F
        self.ms.flags &= (~sasppu.MainState.BG1_ENABLE) & 0xFF
        self.cs.flags &= (~sasppu.CMathState.CMATH_ENABLE) & 0xFF

    def _set_bg1_scroll(self):
        if self._current_line_visually == 1.5:
            self.bg.y = BASE_BG1_Y + LINE_HEIGHT // 2
        elif self._current_line_visually == self._current_line:
            self.bg.y = BASE_BG1_Y + LINE_HEIGHT
        else:
            self.bg.y = int(BASE_BG1_Y + ((self._current_line_visually % 1.0) * LINE_HEIGHT))

    def _write_bg1_map(self):
        for y in range(RESERVED_HEIGHT // 8):
            for x in range(sasppu.MAP_WIDTH):
                end = MAX_LINE_WIDTH // 8
                index = x + (y * sasppu.MAP_WIDTH)
                if x > end:
                    self.bg1[index] = ((0x1FFFF - (sasppu.Background.WIDTH * 8) - 8) // 8) * 4
                else:
                    self.bg1[index] = (((x * 8) + (((y * 8) + RESERVED_START) * sasppu.Background.WIDTH)) // 8) * 4

    def is_open(self) -> bool:
        return self._open
    
    def open(self):
        if not self.is_open():
            self._open = True
            self._ready_event.clear()
    
    def close(self):
        if self.is_open():
            self._cleanup()

    async def write(self, s, stay_open = False):
        await self._ready_event.wait()
        self.set_speech(s)
        self._stay_open = stay_open
        self.open()
        if not self._stay_open:
            await self._ready_event.wait()

    def set_speech(self, speech: str):
        self._lines: list[str] = ["", ""]
        line = ""
        for word in speech.split():
            (x,y) = sasppu.get_text_size(255, line+" "+word, True)
            if x < MAX_LINE_WIDTH:
                line = line + " " + word
            else:
                self._lines.append(line)
                line = word
        if line != "":
            self._lines.append(line)
        if len(self._lines) == 0:
            self._cleanup()
        print(self._lines)
        self._goto_start()
        self._text_update_needed = True

    def _draw_text(self):
        sasppu.fill_background(0, RESERVED_START, 256, RESERVED_HEIGHT, sasppu.TRANSPARENT_BLACK)
        start_index = int(self._current_line)
        for (i, line) in enumerate(self._lines[start_index : start_index + 4]):
            if line == "":
                continue
            width = sasppu.get_text_size(255, line, True)[0]
            offset_left = (MAX_LINE_WIDTH - width) // 2
            sasppu.draw_text_background(offset_left, RESERVED_START + (i * LINE_HEIGHT) - 12, sasppu.WHITE, width, line, True)

    def _goto_start(self):
        if len(self._lines) < 4:
            self._current_line = 0.0
            self._current_line_visually = 0.0
        elif len(self._lines) == 4:
            self._current_line = 1.5
            self._current_line_visually = 1.5
        else:
            self._current_line = 1.0
            self._current_line_visually = 1.0

    def update(self, delta: float):
        if self.is_open():
            if self._state == STATE_CLOSED:
                self._state = STATE_OPENING
                self._opened_amount = 0.0
                self._goto_start()
                eventbus.on(ButtonDownEvent, self._handle_buttondown, self._app)
            if self._state == STATE_OPENING:
                if self._opened_amount > 0.99:
                    self._opened_amount = 1.0
                    self._state = STATE_OPEN
                    return
                weight = math.pow(0.8, (delta/10))
                self._opened_amount = (self._opened_amount * (weight)) + (1-weight)
            elif self._state == STATE_CLOSING:
                if self._opened_amount < 0.02:
                    self._opened_amount = 0.0
                    self._state = STATE_CLOSED
                    self._open = False
                    self._lines = []
                    self._clear_hdma()
                    self._ready_event.set()
                    return
                weight = math.pow(0.8, (delta/10))
                self._opened_amount = self._opened_amount * weight
            if self._current_line_visually != self._current_line:
                weight = math.pow(0.8, (delta/10))
                self._current_line_visually = (self._current_line_visually * (weight)) + (self._current_line * (1-weight))
                if abs(self._current_line_visually - self._current_line) < 0.01:
                    self._current_line_visually = self._current_line

    def draw(self):
        if self.is_open():
            if self._text_update_needed:
                self._text_update_needed = False
                self._draw_text()
            if self._state == STATE_OPENING or self._state == STATE_CLOSING:
                self._fill_hdma()
            if self._current_line_visually != self._current_line:
                self._set_bg1_scroll()
            
    def _handle_buttondown(self, event: ButtonDownEvent):
        if self.is_open() and not self._stay_open:
            if len(self._lines) < 6:
                self._cleanup()
                return
            if self._current_line >= len(self._lines) - 2:
                self._cleanup()
                return
            else:
                self._current_line_visually = self._current_line
                self._current_line += 1.0
                self._text_update_needed = True

    def _cleanup(self):
        eventbus.remove(ButtonDownEvent, self._handle_buttondown, self._app)
        self._state = STATE_CLOSING

class SpeechExample(SASPPUApp):
    def __init__(self):
        super().__init__()
        self.request_fast_updates = True

        sasppu.forced_blank = True

        sasppu.gfx_reset()
        self.ms = sasppu.MainState()
        self.ms.bind()
        self.cs = sasppu.CMathState()
        self.cs.bind()
        self.bg0 = sasppu.Background()
        self.bg0.bind(0)

        self.ms.mainscreen_colour = sasppu.grey555_cmath(20)
        sasppu.fill_background(0, 0, 256, 512, sasppu.BLUE)

        self.speeches = [
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.",
            "Lorem ipsum dolor sit amet,",
            "Lorem ipsum",
        ]
        self.current_speech = 0

        self._speech = SpeechDialog(
            app=self,
            speech=self.speeches[self.current_speech]
        )
        eventbus.on(ButtonDownEvent, self._handle_buttondown, self)

        sasppu.forced_blank = False

    def _handle_buttondown(self, event: ButtonDownEvent):
        if not self._speech.is_open():
            self.current_speech += 1
            self.current_speech %= len(self.speeches)

            self._speech.set_speech(self.speeches[self.current_speech])
            self._speech.open()

    def update(self, delta: float):
        self._speech.update(delta)

    async def background_task(self):
        while True:
            await asyncio.sleep(1)
            print("fps:", display.get_fps(), f"mem used: {gc.mem_alloc()}, mem free:{gc.mem_free()}")

    def draw(self):
        self._speech.draw()
