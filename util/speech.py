import asyncio
import math

from system.eventbus import eventbus
from events.input import ButtonDownEvent
from app import App, SASPPUApp

import sasppu

MAX_LINE_WIDTH = 200
BOX_WIDTH = 200
BOX_HEIGHT = 40

STATE_CLOSED = 0
STATE_CLOSING = 1
STATE_OPEN = 2
STATE_OPENING = 3

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

        self._sasppu_init()
        self.set_speech(speech)

    def _sasppu_init(self):
        self.ms = sasppu.MainState()
        self.ms.bind()
        self.cs = sasppu.CMathState()
        self.cs.bind()
        self.bg = sasppu.Background()
        self.bg.bind(1)
        self.bg1 = sasppu.bg1

        self.bg.windows = (sasppu.WINDOW_ALL) << 4
        self.bg.x = 0
        self.bg.y = 0
        self.bg.flags = 0

        for i in range(240):
            sasppu.hdma_7[i] = None
        sasppu.hdma_enable |= 0x80

        ms = sasppu.MainState()
        ms.bind(False)
        ms.unbind()
        cs = sasppu.CMathState()
        cs.bind(False)
        cs.unbind()

        ms.flags &= (~sasppu.MainState.BG1_ENABLE) &0xFF
        ms.subscreen_colour = sasppu.grey555(20)
        cs.flags &= (~sasppu.CMathState.CMATH_ENABLE) &0xFF
        cs.flags |= sasppu.CMathState.SUB_SUB_SCREEN

        sasppu.hdma_7[0] = ms
        sasppu.hdma_7[1] = cs

        sasppu.hdma_7[140] = ms
        sasppu.hdma_7[144] = cs

        ms.flags |= sasppu.MainState.BG1_ENABLE
        ms.subscreen_colour = sasppu.grey555(10)
        cs.flags |= sasppu.CMathState.CMATH_ENABLE

        sasppu.hdma_7[120] = ms
        sasppu.hdma_7[116] = cs

    def _write_bg1_map(self):
        for y in range(RESERVED_HEIGHT // 8):
            for x in range(240 // 8):
                index = x + (y * self.bg1.WIDTH)
                self.bg1[index] = (x + (y * 64 * 8)) * 4

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
        self._lines: list[str] = []
        line = ""
        for word in speech.split():
            if sasppu.get_text_size(3000, line+" "+word, True) < MAX_LINE_WIDTH:
                line = line + " " + word
            else:
                self._lines.append(line)
                line = word
        if line != "":
            self._lines.append(line)
        if len(self._lines) == 0:
            self._cleanup()
        self._goto_start()

        sasppu.fill_background(0, RESERVED_START, 256, RESERVED_HEIGHT, sasppu.TRANSPARENT_BLACK)

        for (i, line) in enumerate(self._lines)[:4]:
            sasppu.draw_text_background(0, RESERVED_START + (i * LINE_HEIGHT), sasppu.WHITE, MAX_LINE_WIDTH, line, True)

    def _goto_start(self):
        if len(self._lines) < 2:
            self._current_line = 0.0
            self._current_line_visually = 0.0
        elif len(self._lines) == 2:
            self._current_line = 0.5
            self._current_line_visually = 0.5
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
                if self._opened_amount < 0.01:
                    self._opened_amount = 0.0
                    self._state = STATE_CLOSED
                    self._open = False
                    self._lines = []
                    self._ready_event.set()
                    return
                weight = math.pow(0.8, (delta/10))
                self._opened_amount = self._opened_amount * weight
            if self._current_line_visually != self._current_line:
                weight = math.pow(0.8, (delta/10))
                self._current_line_visually = (self._current_line_visually * (weight)) + (self._current_line * (1-weight))

    def draw(self):
        pass
            
    def _handle_buttondown(self, event: ButtonDownEvent):
        if self.is_open() and not self._stay_open:
            if len(self._lines) < 4:
                self._cleanup()
                return
            if self._current_line >= len(self._lines) -1:
                self._cleanup()
                return
            else:
                self._current_line += 1

    def _cleanup(self):
        eventbus.remove(ButtonDownEvent, self._handle_buttondown, self._app)
        self._state = STATE_CLOSING

class SpeechExample(SASPPUApp):
    def __init__(self):
        super().__init__()
        self.request_fast_updates = True

        self.ms = sasppu.MainState()
        self.ms.bind()
        self.cs = sasppu.CMathState()
        self.cs.bind()
        self.bg0 = sasppu.Background()
        self.bg0.bind(0)

        self.ms.mainscreen_colour = sasppu.grey555(29)

        self._speech = SpeechDialog(
            app=self,
            speech="Lorem ipsum dolor sit amet, consectetur adipiscing elit" #, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum."
        )
        eventbus.on(ButtonDownEvent, self._handle_buttondown, self)

    def _handle_buttondown(self, event: ButtonDownEvent):
        self._speech.open()

    def update(self, delta: float):
        self._speech.update(delta)

    def draw(self):
        self._speech.draw()
