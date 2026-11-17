#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
C de Soirée – "Qui de nous…"
Application Kivy multi-joueurs réseau local
Version Finale - Layout Fixé, Texte Visible et Stable (PC & Tablettes)
"""

import json
import socket
import threading
import time

import kivy
kivy.require('2.0.0')

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen, FadeTransition
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.utils import platform

try:
    from plyer import accelerometer
    HAS_ACCEL = True
except Exception as _e:
    print(f"[Capteurs indisponibles : {_e}]")
    HAS_ACCEL = False

# ── Palette ───────────────────────────────────────────────────────────────────
BG_DARK   = (0.05, 0.04, 0.08, 1)
SURFACE   = (0.12, 0.10, 0.20, 1)
PRIMARY   = (0.55, 0.15, 0.95, 1)
SECONDARY = (0.18, 0.15, 0.30, 1)
ACCENT    = (0.00, 0.90, 0.85, 1)
TEXT_MAIN = (1.00, 1.00, 1.00, 1)
TEXT_MUTED= (0.65, 0.60, 0.75, 1)
SUCCESS   = (0.00, 0.80, 0.40, 1)
ERROR     = (1.00, 0.25, 0.40, 1)
SEL       = (0.05, 0.55, 0.25, 1)

Window.clearcolor = BG_DARK
Window.orientation = 'portrait'

# ── Son ───────────────────────────────────────────────────────────────────────
try:
    import numpy as np
    import pygame
    pygame.mixer.init(44100, -16, 1, 1024)

    def _build_victory():
        sr = 44100; dur = 4.0
        t = np.linspace(0, dur, int(sr * dur), False)
        notes = [261.63, 329.63, 392.00, 523.25, 659.25, 783.99, 1046.50]
        wave = np.zeros(len(t))
        nd = dur / len(notes)
        for i, f in enumerate(notes):
            s, e = int(i * nd * sr), int((i + 1) * nd * sr)
            env = np.exp(-2.5 * np.linspace(0, 1, e - s))
            wave[s:e] += np.sin(2 * np.pi * f * t[s:e]) * env * 0.5
        return pygame.sndarray.make_sound((np.clip(wave, -1, 1) * 32767).astype(np.int16))

    VICTORY_SFX = _build_victory()
    HAS_SOUND = True
except Exception as _e:
    print(f"[Son désactivé : {_e}]")
    VICTORY_SFX = None
    HAS_SOUND = False


# ── Réseau ────────────────────────────────────────────────────────────────────
def get_interfaces():
    results = []
    try:
        import psutil
        stats = psutil.net_if_stats()
        for iface, addrs in psutil.net_if_addrs().items():
            if iface in stats and not stats[iface].isup:
                continue
            for a in addrs:
                if a.family == socket.AF_INET and not a.address.startswith('127.'):
                    results.append((iface, a.address))
    except ImportError:
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None):
                ip = info[4][0]
                if ':' not in ip and not ip.startswith('127.') and ip not in [r[1] for r in results]:
                    results.append(('Interface', ip))
        except Exception:
            pass
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80)); fb = s.getsockname()[0]; s.close()
            if fb not in [r[1] for r in results] and not fb.startswith('127.'):
                results.insert(0, ('Wi-Fi/Ethernet', fb))
        except Exception:
            pass

    def priority(item):
        n = item[0].lower()
        if any(k in n for k in ('wi-fi', 'wifi', 'wlan', 'wireless', 'wi_fi')): return 0
        if any(k in n for k in ('ethernet', 'eth', 'local area')): return 1
        return 5

    results.sort(key=priority)
    return results if results else [('Aucune interface', '127.0.0.1')]


PORT = 55_555
MAX_ROUNDS = 5


class G:
    name = ""; is_host = False; players = []; scores = {}
    cur_round = 0; questioner = ""; question = ""; q_answer = ""
    my_vote = ""; all_votes = {}; winner = ""; host_ip = "127.0.0.1"
    interfaces = []; server_sock = None; client_sock = None
    peers = {}; results_done = False; _lock = threading.Lock()


def net_send(sock, msg):
    try:
        data = json.dumps(msg, ensure_ascii=False).encode()
        sock.sendall(len(data).to_bytes(4, 'big') + data)
        return True
    except Exception as e:
        print("send err:", e); return False


def net_recv(sock):
    try:
        hdr = b""
        while len(hdr) < 4:
            c = sock.recv(4 - len(hdr))
            if not c: return None
            hdr += c
        n = int.from_bytes(hdr, 'big')
        data = b""
        while len(data) < n:
            c = sock.recv(min(4096, n - len(data)))
            if not c: return None
            data += c
        return json.loads(data.decode())
    except Exception as e:
        print("recv err:", e); return None


def bcast(msg, exclude=None):
    with G._lock:
        for name, s in list(G.peers.items()):
            if name != exclude:
                net_send(s, msg)


# ── Composants ────────────────────────────────────────────────────────────────

class CardLayout(BoxLayout):
    def __init__(self, bg_color=SURFACE, radius=16, **kwargs):
        super().__init__(**kwargs)
        self.bg_color = bg_color; self.radius = radius
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *_):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*self.bg_color)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[self.radius])


class SmoothButton(Button):
    def __init__(self, bg_color=PRIMARY, radius=12, font_size=16, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''; self.background_down = ''
        self.background_color = (0, 0, 0, 0)
        self.bg_color = bg_color; self.radius = radius
        self.font_size = font_size; self.bold = True; self.color = TEXT_MAIN
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *_):
        self.canvas.before.clear()
        with self.canvas.before:
            color = [c * 1.15 for c in self.bg_color[:3]] + [self.bg_color[3]] \
                if self.state == 'down' else self.bg_color
            Color(*color)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[self.radius])


class ModernInput(TextInput):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''; self.background_active = ''
        self.background_color = (0.18, 0.15, 0.30, 1)
        self.multiline = False; self.cursor_color = ACCENT
        self.cursor_width = 2; self.hint_text_color = TEXT_MUTED
        self.foreground_color = TEXT_MAIN; self.font_size = 18
        self.padding = [16, 14, 16, 14]


def mk_lbl(text, fs=16, color=TEXT_MAIN, bold=False, **kw):
    return Label(text=text, font_size=fs, color=color, bold=bold, font_name="Roboto", **kw)

def mk_title(text, fs=28):
    return Label(text=text, font_size=fs, color=ACCENT, bold=True,
                 size_hint_y=None, height=55, halign='center')

def spacer(h=0.05):
    return Widget(size_hint_y=h)


# ── Menu ──────────────────────────────────────────────────────────────────────
class MenuScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        root = BoxLayout(orientation='vertical', padding=[30, 40, 30, 30], spacing=10)

        root.add_widget(spacer(0.05))
        root.add_widget(mk_title('QUI DE NOUS...', fs=34))
        root.add_widget(mk_lbl('Jeu de questions entre amis', fs=14, color=TEXT_MUTED,
                                size_hint_y=None, height=25, halign='center'))
        root.add_widget(spacer(0.04))

        card = CardLayout(orientation='vertical', padding=20, spacing=12,
                          size_hint_y=None, height=330)
        card.add_widget(mk_lbl('VOTRE PRENOM / PSEUDO :', fs=14, bold=True,
                                size_hint_y=None, height=25))
        self.ni = ModernInput(hint_text='Joueur 1', size_hint_y=None, height=50)
        card.add_widget(self.ni)
        card.add_widget(SmoothButton(text='Creer une partie (Hote)', bg_color=PRIMARY,
                                     font_size=16, size_hint_y=None, height=52,
                                     on_press=self.do_host))
        card.add_widget(mk_lbl('— OU REJOINDRE —', fs=12, color=TEXT_MUTED, bold=True,
                                size_hint_y=None, height=20, halign='center'))
        card.add_widget(mk_lbl("ADRESSE IP DE L'HOTE :", fs=13, bold=True,
                                size_hint_y=None, height=25))
        self.ip = ModernInput(hint_text='127.0.0.1', size_hint_y=None, height=50)
        card.add_widget(self.ip)
        card.add_widget(SmoothButton(text='Rejoindre la partie', bg_color=SECONDARY,
                                     font_size=16, size_hint_y=None, height=52,
                                     on_press=self.do_join))
        root.add_widget(card)

        root.add_widget(spacer(0.04))
        self.err = mk_lbl('', fs=14, color=ERROR, size_hint_y=None, height=30,
                          halign='center')
        root.add_widget(self.err)
        root.add_widget(spacer())
        root.add_widget(mk_lbl('Matteo Pozzo di Borgo & Mathis Bento', fs=11,
                                color=TEXT_MUTED, size_hint_y=None, height=20,
                                halign='center'))
        self.add_widget(root)

    def _name(self):
        n = self.ni.text.strip()
        if not n: self.err.text = 'Entrez votre prenom !'; return None
        return n

    def do_host(self, *_):
        name = self._name()
        if not name: return
        G.name = name; G.is_host = True
        G.players = [name]; G.scores = {name: 0}; G.peers = {}
        G.interfaces = get_interfaces(); G.host_ip = G.interfaces[0][1]
        self._start_server()
        self.manager.current = 'lobby'

    def _start_server(self):
        def run():
            srv = socket.socket()
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(('', PORT)); srv.listen(10); G.server_sock = srv
            while True:
                try:
                    conn, _ = srv.accept()
                    threading.Thread(target=self._peer, args=(conn,), daemon=True).start()
                except: break
        threading.Thread(target=run, daemon=True).start()

    def _peer(self, conn):
        msg = net_recv(conn)
        if not msg or msg['type'] != 'join': conn.close(); return
        name = msg['name']; base = name; i = 2
        while name in G.players: name = f"{base}_{i}"; i += 1
        with G._lock:
            G.players.append(name); G.scores[name] = 0; G.peers[name] = conn
        bcast({'type': 'player_list', 'players': G.players})
        Clock.schedule_once(lambda *_: self._refresh_lobby(), 0)
        while True:
            m = net_recv(conn)
            if not m: break
            Clock.schedule_once(lambda *_, mm=m, sn=name:
                                App.get_running_app().host_recv(mm, sn), 0)
        with G._lock:
            G.peers.pop(name, None)
            if name in G.players: G.players.remove(name)
        bcast({'type': 'player_list', 'players': G.players})
        Clock.schedule_once(lambda *_: self._refresh_lobby(), 0)

    def _refresh_lobby(self):
        if 'lobby' in self.manager.screen_names:
            self.manager.get_screen('lobby').refresh_players()

    def do_join(self, *_):
        name = self._name()
        if not name: return
        G.name = name; G.is_host = False
        G.host_ip = self.ip.text.strip() or '127.0.0.1'
        self.err.text = 'Connexion...'; self.err.color = ACCENT
        threading.Thread(target=self._connect, daemon=True).start()

    def _connect(self):
        try:
            s = socket.socket(); s.settimeout(5)
            s.connect((G.host_ip, PORT)); s.settimeout(None)
            G.client_sock = s
            net_send(s, {'type': 'join', 'name': G.name})
            Clock.schedule_once(lambda *_: setattr(self.manager, 'current', 'lobby'), 0)
            while True:
                m = net_recv(s)
                if not m: break
                Clock.schedule_once(lambda *_, mm=m:
                                    App.get_running_app().client_recv(mm), 0)
        except socket.timeout:
            Clock.schedule_once(lambda *_: setattr(self.err, 'text', f'Timeout TCP {PORT}'), 0)
        except ConnectionRefusedError:
            Clock.schedule_once(lambda *_: setattr(self.err, 'text', 'Connexion refusee'), 0)
        except Exception as e:
            Clock.schedule_once(lambda *_, err=str(e): setattr(self.err, 'text', f'Erreur : {err}'), 0)


# ── Lobby ─────────────────────────────────────────────────────────────────────
class LobbyScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self._ip_btns = []; self._shake_thread_active = False

        root = BoxLayout(orientation='vertical', padding=[20, 30, 20, 20], spacing=12)

        root.add_widget(mk_title('SALON D\'ATTENTE'))
        root.add_widget(spacer(0.02))

        self.ip_block = BoxLayout(orientation='vertical', size_hint_y=None, height=0, spacing=6)
        root.add_widget(self.ip_block)

        root.add_widget(mk_lbl('Joueurs prets dans la room :', fs=15, bold=True,
                                size_hint_y=None, height=28))

        self.card_list = CardLayout(orientation='vertical', padding=10, spacing=5,
                                    size_hint_y=0.4)
        sv = ScrollView()
        self.plist = GridLayout(cols=1, spacing=8, size_hint_y=None)
        self.plist.bind(minimum_height=self.plist.setter('height'))
        sv.add_widget(self.plist)
        self.card_list.add_widget(sv)
        root.add_widget(self.card_list)

        root.add_widget(spacer(0.02))

        self.accel_status_card = CardLayout(orientation='vertical', padding=12,
                                            bg_color=SECONDARY, radius=12,
                                            size_hint_y=None, height=56)
        self.accel_lbl = mk_lbl('Capteur en attente...', fs=15, color=TEXT_MUTED, bold=True,
                                 halign='center')
        self.accel_status_card.add_widget(self.accel_lbl)
        root.add_widget(self.accel_status_card)

        self.status = mk_lbl('En attente...', fs=13, color=TEXT_MUTED,
                              size_hint_y=None, height=25, halign='center')
        root.add_widget(self.status)

        root.add_widget(spacer())
        root.add_widget(SmoothButton(text='Retour au menu', bg_color=ERROR,
                                     font_size=14, size_hint_y=None, height=46,
                                     on_press=self._back_to_menu))
        self.add_widget(root)

    def _back_to_menu(self, *_):
        self._stop_shake_detection()
        try:
            if G.server_sock: G.server_sock.close()
            if G.client_sock: G.client_sock.close()
        except: pass
        G.name = ''; G.is_host = False; G.players = []
        G.scores = {}; G.peers = {}; G.interfaces = []
        G.server_sock = None; G.client_sock = None
        self.manager.current = 'menu'

    def on_enter(self):
        self._build_ip_block(); self.refresh_players()
        if G.is_host: self._start_shake_detection()
        else: self.accel_lbl.text = "Attente du signal de l'hote..."

    def on_leave(self):
        self._stop_shake_detection()

    def _build_ip_block(self):
        self.ip_block.clear_widgets(); self._ip_btns = []
        if not G.is_host:
            self.ip_block.height = 40
            self.ip_block.add_widget(mk_lbl(f'Connecte au serveur : {G.host_ip}',
                                            fs=13, color=SUCCESS, halign='center'))
            return
        ifaces = G.interfaces
        self.ip_block.height = 28 + len(ifaces) * 50
        self.ip_block.add_widget(mk_lbl('IP a partager :', fs=13, color=ACCENT,
                                         size_hint_y=None, height=24))
        for iface_name, ip in ifaces:
            row = BoxLayout(orientation='horizontal', size_hint_y=None, height=44, padding=(10, 0))
            is_sel = (ip == G.host_ip)
            b = SmoothButton(text=f"{iface_name} : {ip}",
                             bg_color=SEL if is_sel else SECONDARY, font_size=13)
            b.bind(on_press=lambda bw, i=ip: self._select_ip(i))
            row.add_widget(b)
            self.ip_block.add_widget(row)
            self._ip_btns.append((ip, b))

    def _select_ip(self, ip):
        G.host_ip = ip
        for stored, btn in self._ip_btns:
            btn.bg_color = SEL if stored == ip else SECONDARY
            btn._upd()

    def refresh_players(self):
        self.plist.clear_widgets()
        for p in G.players:
            icon = '(H)' if p == G.players[0] else '>'
            lbl_color = ACCENT if p == G.name else TEXT_MAIN
            row = CardLayout(orientation='horizontal', bg_color=SECONDARY, radius=8,
                             size_hint_y=None, height=46, padding=[15, 0, 15, 0])
            row.add_widget(mk_lbl(f'{icon}  {p}', fs=15, color=lbl_color,
                                  bold=(p == G.name)))
            self.plist.add_widget(row)
        n = len(G.players)
        self.status.text = f'Salon actif ({n} joueurs)' if n >= 2 \
            else f'Requis : au moins 2 joueurs ({n}/2)'

    def _start_shake_detection(self):
        if not HAS_ACCEL:
            self.accel_lbl.text = "Accelerometre absent"; self.accel_lbl.color = ERROR; return
        try:
            accelerometer.enable(); self._shake_thread_active = True
            self.accel_lbl.text = "SECOUEZ POUR LANCER"; self.accel_lbl.color = ACCENT
            threading.Thread(target=self._shake_loop, daemon=True).start()
        except Exception:
            self.accel_lbl.text = "Erreur capteur"; self.accel_lbl.color = ERROR

    def _stop_shake_detection(self):
        self._shake_thread_active = False
        if HAS_ACCEL:
            try: accelerometer.disable()
            except: pass

    def _shake_loop(self):
        lx = ly = lz = None
        while self._shake_thread_active:
            try:
                val = accelerometer.acceleration
                if val and None not in val:
                    x, y, z = val
                    if lx is not None:
                        if abs(x-lx)+abs(y-ly)+abs(z-lz) > 14.5:
                            Clock.schedule_once(lambda *_: self._trigger_start(), 0); break
                    lx, ly, lz = x, y, z
            except: pass
            time.sleep(0.05)

    def _trigger_start(self):
        if len(G.players) < 2:
            self.status.text = 'Deux joueurs minimum !'; self.status.color = ERROR
            if self._shake_thread_active:
                threading.Thread(target=self._shake_loop, daemon=True).start()
            return
        self.accel_lbl.text = "CHARGEMENT..."; self.accel_lbl.color = SUCCESS
        G.cur_round = 0; G.scores = {p: 0 for p in G.players}
        bcast({'type': 'game_start', 'players': G.players})
        App.get_running_app().next_round()


# ── Question ──────────────────────────────────────────────────────────────────
class QuestionScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.root_box = BoxLayout(orientation='vertical', padding=[20, 30, 20, 20], spacing=12)
        self.add_widget(self.root_box)

    def on_enter(self):
        self.root_box.clear_widgets()
        self.root_box.add_widget(mk_title(f'MANCHE {G.cur_round} / {MAX_ROUNDS}', fs=24))
        self.root_box.add_widget(spacer(0.03))
        if G.questioner == G.name: self._build_questioner()
        else: self._build_waiting()

    def _build_questioner(self):
        self.root_box.add_widget(mk_lbl("Complete l'affirmation :", fs=15,
                                         color=ACCENT, bold=True, size_hint_y=None, height=28))
        self.root_box.add_widget(mk_lbl('« Qui de nous... »', fs=20, bold=True,
                                         size_hint_y=None, height=38))
        self.qi = ModernInput(hint_text='...est le plus susceptible ?',
                              size_hint_y=None, height=52)
        self.root_box.add_widget(self.qi)
        self.root_box.add_widget(spacer(0.02))
        self.root_box.add_widget(mk_lbl('Selectionne ton choix secret :', fs=14,
                                         color=TEXT_MUTED, size_hint_y=None, height=25))
        self._sel = [None]; self._abtns = []
        grid = GridLayout(cols=2, spacing=10, size_hint_y=None, height=120)
        for p in [x for x in G.players if x != G.name]:
            b = SmoothButton(text=p, bg_color=SECONDARY, font_size=14)
            b.bind(on_press=lambda bw, pn=p: self._pick(pn))
            grid.add_widget(b); self._abtns.append((p, b))
        self.root_box.add_widget(grid)
        self.errlbl = mk_lbl('', fs=14, color=ACCENT, size_hint_y=None, height=28,
                              halign='center')
        self.root_box.add_widget(self.errlbl)
        self.root_box.add_widget(spacer())
        self.root_box.add_widget(SmoothButton(text='VALIDER LA QUESTION', bg_color=PRIMARY,
                                               size_hint_y=None, height=54,
                                               on_press=self._submit))

    def _pick(self, name):
        self._sel[0] = name
        for p, b in self._abtns:
            b.bg_color = PRIMARY if p == name else SECONDARY; b._upd()
        self.errlbl.text = f'Cible : {name}'; self.errlbl.color = SUCCESS

    def _submit(self, *_):
        q = self.qi.text.strip()
        if not q: self.errlbl.text = 'Complete le texte !'; return
        if not self._sel[0]: self.errlbl.text = 'Choisis un joueur !'; return
        G.question = q; G.q_answer = self._sel[0]
        if G.is_host:
            G.all_votes = {}
            bcast({'type': 'start_vote', 'question': q, 'questioner': G.questioner,
                   'players': G.players, 'round': G.cur_round})
            App.get_running_app().go_vote()
        else:
            net_send(G.client_sock, {'type': 'question_set', 'question': q,
                                      'answer': self._sel[0]})
            self.errlbl.text = 'Envoye ! Attente...'; self.errlbl.color = SUCCESS

    def _build_waiting(self):
        self.root_box.add_widget(spacer(0.1))
        card = CardLayout(orientation='vertical', padding=25, spacing=15,
                          size_hint_y=None, height=160)
        card.add_widget(mk_lbl(f'{G.questioner}', fs=22, color=ACCENT, bold=True,
                                halign='center'))
        card.add_widget(mk_lbl('redige la question...', fs=16, halign='center'))
        self.root_box.add_widget(card)


# ── Vote ──────────────────────────────────────────────────────────────────────
class VoteScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.root_box = BoxLayout(orientation='vertical', padding=[20, 30, 20, 20], spacing=12)
        self.add_widget(self.root_box)

    def on_enter(self):
        self.root_box.clear_widgets()
        self.root_box.add_widget(mk_title(f'MANCHE {G.cur_round} / {MAX_ROUNDS}', fs=24))
        self.root_box.add_widget(spacer(0.02))

        q_card = CardLayout(orientation='vertical', padding=15, bg_color=PRIMARY,
                            size_hint_y=None, height=100)
        ql = mk_lbl(f'« Qui de nous {G.question} »', fs=17, bold=True,
                    halign='center')
        ql.text_size = (Window.width - 80, None)
        q_card.add_widget(ql)
        self.root_box.add_widget(q_card)

        self.root_box.add_widget(mk_lbl(f'Propose par : {G.questioner}', fs=13,
                                         color=TEXT_MUTED, size_hint_y=None,
                                         height=22, halign='center'))
        self.root_box.add_widget(spacer(0.02))

        if G.questioner == G.name:
            self._wlbl = mk_lbl('En attente des votes...', fs=18, color=ACCENT,
                                  bold=True, size_hint_y=None, height=40, halign='center')
            self.root_box.add_widget(self._wlbl)
            Clock.schedule_interval(self._tick, 0.5)
        else:
            self.root_box.add_widget(mk_lbl('Vote pour une personne :', fs=15,
                                             size_hint_y=None, height=28))
            self._vbtns = []
            grid = GridLayout(cols=2, spacing=10, size_hint_y=None, height=130)
            for p in [x for x in G.players if x != G.questioner]:
                b = SmoothButton(text=p, bg_color=SECONDARY)
                b.bind(on_press=lambda bw, pn=p: self._vote(pn))
                grid.add_widget(b); self._vbtns.append((p, b))
            self.root_box.add_widget(grid)
            self._vstatus = mk_lbl('', fs=15, color=SUCCESS,
                                    size_hint_y=None, height=30, halign='center')
            self.root_box.add_widget(self._vstatus)

    def _tick(self, *_):
        if hasattr(self, '_wlbl'):
            n = len(G.all_votes)
            exp = len([p for p in G.players if p != G.questioner])
            self._wlbl.text = f'Votes recus : {n} / {exp}'

    def _vote(self, name):
        if G.my_vote: return
        G.my_vote = name
        for p, b in self._vbtns:
            b.bg_color = SUCCESS if p == name else SECONDARY
            b.disabled = True; b.opacity = 1 if p == name else 0.4; b._upd()
        self._vstatus.text = f'Vote envoye pour {name} !'
        if G.is_host:
            G.all_votes[G.name] = name; App.get_running_app().check_results()
        else:
            net_send(G.client_sock, {'type': 'vote', 'voted_for': name})

    def on_leave(self):
        Clock.unschedule(self._tick)


# ── Résultats ─────────────────────────────────────────────────────────────────
class ResultsScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.root_box = BoxLayout(orientation='vertical', padding=[20, 30, 20, 20], spacing=10)
        self.add_widget(self.root_box)

    def on_enter(self):
        self.root_box.clear_widgets()
        self.root_box.add_widget(mk_title('RESULTATS DE LA MANCHE', fs=22))
        self.root_box.add_widget(spacer(0.02))

        ans_card = CardLayout(orientation='horizontal', padding=10, bg_color=SECONDARY,
                              radius=8, size_hint_y=None, height=46)
        ans_card.add_widget(mk_lbl(f'Choix de {G.questioner} : {G.q_answer}',
                                    fs=15, color=ACCENT, bold=True, halign='center'))
        self.root_box.add_widget(ans_card)
        self.root_box.add_widget(spacer(0.02))

        self.root_box.add_widget(mk_lbl('Votes :', fs=14, bold=True,
                                         size_hint_y=None, height=24))
        sv_votes = ScrollView(size_hint_y=0.35)
        vl = GridLayout(cols=1, spacing=6, size_hint_y=None)
        vl.bind(minimum_height=vl.setter('height'))
        for voter, voted_for in G.all_votes.items():
            ok = (voted_for == G.q_answer)
            v_row = CardLayout(orientation='horizontal', bg_color=SURFACE, radius=6,
                               size_hint_y=None, height=40, padding=[12, 0, 12, 0])
            v_row.add_widget(mk_lbl(f'{"OK" if ok else "X"}  {voter} -> {voted_for}',
                                     fs=14, color=SUCCESS if ok else TEXT_MAIN))
            vl.add_widget(v_row)
        sv_votes.add_widget(vl)
        self.root_box.add_widget(sv_votes)

        self.root_box.add_widget(mk_lbl('Scores :', fs=14, bold=True,
                                         size_hint_y=None, height=24))
        sv_scores = ScrollView(size_hint_y=0.28)
        sl = GridLayout(cols=1, spacing=5, size_hint_y=None)
        sl.bind(minimum_height=sl.setter('height'))
        for p, sc in sorted(G.scores.items(), key=lambda x: x[1], reverse=True):
            s_row = CardLayout(orientation='horizontal', bg_color=SECONDARY, radius=6,
                               size_hint_y=None, height=38, padding=[12, 0, 12, 0])
            s_row.add_widget(mk_lbl(p, fs=14, color=ACCENT if p == G.name else TEXT_MAIN))
            s_row.add_widget(mk_lbl(f'{sc} pts', fs=14, bold=True))
            sl.add_widget(s_row)
        sv_scores.add_widget(sl)
        self.root_box.add_widget(sv_scores)

        self.root_box.add_widget(spacer())
        if G.is_host:
            self.root_box.add_widget(SmoothButton(text='CONTINUER', bg_color=PRIMARY,
                                                   size_hint_y=None, height=52,
                                                   on_press=lambda *_: App.get_running_app().next_round()))
        else:
            self.root_box.add_widget(mk_lbl("L'hote va lancer la suite...", fs=14,
                                             color=TEXT_MUTED, size_hint_y=None,
                                             height=45, halign='center'))


# ── Victoire ──────────────────────────────────────────────────────────────────
class VictoryScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.root_box = BoxLayout(orientation='vertical', padding=[20, 40, 20, 30], spacing=15)
        self.add_widget(self.root_box)

    def on_enter(self):
        self.root_box.clear_widgets()
        if HAS_SOUND and VICTORY_SFX:
            try: VICTORY_SFX.play()
            except: pass

        self.root_box.add_widget(mk_lbl('***', fs=56, size_hint_y=None,
                                         height=65, halign='center'))
        self.root_box.add_widget(mk_title('PARTIE TERMINEE !', fs=26))
        self.root_box.add_widget(spacer(0.03))

        v_card = CardLayout(orientation='vertical', padding=15, bg_color=PRIMARY,
                            size_hint_y=None, height=90)
        v_card.add_widget(mk_lbl('VAINQUEUR', fs=13, halign='center'))
        v_card.add_widget(mk_lbl(G.winner, fs=24, bold=True, halign='center'))
        self.root_box.add_widget(v_card)
        self.root_box.add_widget(spacer(0.02))

        self.root_box.add_widget(mk_lbl('Classement :', fs=14, bold=True,
                                         size_hint_y=None, height=26))
        sv = ScrollView(size_hint_y=0.45)
        ll = GridLayout(cols=1, spacing=6, size_hint_y=None)
        ll.bind(minimum_height=ll.setter('height'))
        medals = ['[1]', '[2]', '[3]']
        for i, (p, sc) in enumerate(sorted(G.scores.items(), key=lambda x: x[1], reverse=True)):
            med = medals[i] if i < 3 else '-'
            r_row = CardLayout(orientation='horizontal', bg_color=SURFACE, radius=8,
                               size_hint_y=None, height=44, padding=[15, 0, 15, 0])
            r_row.add_widget(mk_lbl(f'{med}  {p}', fs=15,
                                     color=ACCENT if i == 0 else TEXT_MAIN))
            r_row.add_widget(mk_lbl(f'{sc} Pts', fs=14, bold=True))
            ll.add_widget(r_row)
        sv.add_widget(ll)
        self.root_box.add_widget(sv)

        self.root_box.add_widget(spacer())
        self.root_box.add_widget(SmoothButton(text='RETOUR AU MENU', bg_color=SECONDARY,
                                               size_hint_y=None, height=52,
                                               on_press=self._replay))

    def _replay(self, *_):
        try:
            if G.server_sock: G.server_sock.close()
            if G.client_sock: G.client_sock.close()
        except: pass
        G.name = ''; G.is_host = False; G.players = []; G.scores = {}
        G.cur_round = 0; G.questioner = ''; G.question = ''; G.q_answer = ''
        G.my_vote = ''; G.all_votes = {}; G.winner = ''
        G.server_sock = None; G.client_sock = None; G.peers = {}; G.interfaces = []
        self.manager.current = 'menu'


# ── App ───────────────────────────────────────────────────────────────────────
class JeuDeSoireeApp(App):
    def build(self):
        if platform == 'android':
            try:
                from android.permissions import request_permissions, Permission
                request_permissions([Permission.INTERNET])
            except Exception as e:
                print(f"[Permissions] Erreur : {e}")

        sm = ScreenManager(transition=FadeTransition(duration=.18))
        for name, cls in [('menu', MenuScreen), ('lobby', LobbyScreen),
                          ('question', QuestionScreen), ('vote', VoteScreen),
                          ('results', ResultsScreen), ('victory', VictoryScreen)]:
            sm.add_widget(cls(name=name))
        return sm

    def host_recv(self, msg, sender):
        t = msg.get('type')
        if t == 'question_set':
            G.question = msg['question']; G.q_answer = msg['answer']
            G.all_votes = {}; G.results_done = False
            bcast({'type': 'start_vote', 'question': G.question, 'questioner': G.questioner,
                   'players': G.players, 'round': G.cur_round})
            self.go_vote()
        elif t == 'vote':
            G.all_votes[sender] = msg['voted_for']; self.check_results()

    def client_recv(self, msg):
        t = msg.get('type'); sm = self.root
        if t == 'player_list':
            G.players = msg['players']
            if sm.current == 'lobby': sm.get_screen('lobby').refresh_players()
        elif t == 'game_start':
            G.players = msg['players']; G.scores = {p: 0 for p in G.players}; self.next_round()
        elif t == 'next_round':
            G.cur_round = msg['round']; G.questioner = msg['questioner']
            G.my_vote = ''; G.all_votes = {}; G.results_done = False; sm.current = 'question'
        elif t == 'start_vote':
            G.question = msg['question']; G.questioner = msg['questioner']
            G.cur_round = msg['round']; G.my_vote = ''; self.go_vote()
        elif t == 'round_results':
            G.q_answer = msg['questioner_answer']; G.all_votes = msg['votes']
            G.scores = msg['scores']; sm.current = 'results'
        elif t == 'game_over':
            G.winner = msg['winner']; G.scores = msg['scores']; sm.current = 'victory'

    def next_round(self):
        G.cur_round += 1; G.all_votes = {}; G.my_vote = ''; G.results_done = False
        if G.cur_round > MAX_ROUNDS:
            winner = max(G.scores, key=G.scores.get); G.winner = winner
            bcast({'type': 'game_over', 'winner': winner, 'scores': G.scores})
            self.root.current = 'victory'; return
        G.questioner = G.players[(G.cur_round - 1) % len(G.players)]
        bcast({'type': 'next_round', 'round': G.cur_round, 'questioner': G.questioner})
        self.root.current = 'question'

    def go_vote(self):
        G.my_vote = ''; self.root.current = 'vote'

    def check_results(self):
        if G.results_done: return
        expected = [p for p in G.players if p != G.questioner]
        if not all(v in G.all_votes for v in expected): return
        G.results_done = True; self.compute_results()

    def compute_results(self):
        for voter, voted_for in G.all_votes.items():
            if voted_for == G.q_answer:
                G.scores[voter] = G.scores.get(voter, 0) + 1
        bcast({'type': 'round_results', 'questioner_answer': G.q_answer,
               'votes': G.all_votes, 'scores': G.scores})
        self.root.current = 'results'


if __name__ == '__main__':
    JeuDeSoireeApp().run()