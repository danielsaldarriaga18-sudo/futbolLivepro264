"""Fútbol Live Pro: aplicación Windows nativa, sin HTTP ni navegador."""
import asyncio
import copy
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import Qt, QRect, QTimer, QThread, Signal, QUrl, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QPixmap, QLinearGradient
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QLineEdit, QSpinBox, QComboBox, QCheckBox, QMessageBox,
    QFormLayout, QGroupBox, QAbstractItemView, QSplitter, QScrollArea)

NAMES = ['Atlético Nacional', 'Independiente Medellín', 'Millonarios',
 'Independiente Santa Fe', 'América de Cali', 'Deportivo Cali', 'Junior',
 'Once Caldas', 'Deportes Tolima', 'Atlético Bucaramanga', 'Deportivo Pereira',
 'Deportivo Pasto', 'Águilas Doradas', 'Alianza FC', 'Fortaleza CEIF',
 'Llaneros FC', 'Jaguares de Córdoba', 'Boyacá Chicó', 'Cúcuta Deportivo',
 'Internacional de Bogotá']

BASE = Path(os.environ.get('APPDATA') or (Path.home() / '.config')) / 'FutbolLivePro'
DATA = BASE / 'datos.json'

def defaults():
    return {'teams': [{'name': n, 'points': 0, 'gift': 'Rosa', 'value': 10,
                       'logo': '', 'active': True} for n in NAMES],
            'settings': {'seconds': 180, 'mode': 'elimination', 'api_key': '',
                         'league_id': '', 'season': 2026, 'refresh': 15,
                         'live_user': '', 'transparent': False},
            'league': [], 'league_updated': '', 'league_error': 'Sin sincronizar',
            'event': {'type': 'ready', 'text': '¡BIENVENIDOS AL ESTADIO!', 'ts': 0},
            'running': False, 'deadline': 0, 'remaining': 180, 'history': []}

def load_data():
    state = defaults()
    candidates = [DATA, Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent / 'datos.json']
    for p in candidates:
        if p.is_file():
            try:
                raw = json.loads(p.read_text(encoding='utf-8'))
                if isinstance(raw, dict):
                    state.update({k: v for k, v in raw.items() if k in state})
                    state['settings'] = {**defaults()['settings'], **raw.get('settings', {})}
                    break
            except (OSError, ValueError, TypeError):
                continue
    # No reanudar automáticamente una eliminación después de cerrar el programa.
    state['running'] = False
    state['remaining'] = max(1, int(state.get('remaining') or state['settings']['seconds']))
    return state

class Store:
    def __init__(self):
        self.data = load_data()
        self.listeners = []
        self.last_event = ''

    def notify(self):
        for fn in list(self.listeners):
            fn()

    def save(self):
        BASE.mkdir(parents=True, exist_ok=True)
        temp = DATA.with_suffix('.tmp')
        temp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding='utf-8')
        temp.replace(DATA)
        self.notify()

    def event(self, kind, msg):
        e = {'type': kind, 'text': msg, 'ts': time.time()}
        self.data['event'] = e
        self.data['history'] = (self.data.get('history', []) + [e])[-100:]

    def sorted_teams(self):
        return sorted(self.data['teams'], key=lambda x: (not x['active'], -int(x['points']), x['name']))

    def remaining(self):
        if self.data['running']:
            return max(0, int(self.data['deadline'] - time.time() + .999))
        return max(0, int(self.data.get('remaining', self.data['settings']['seconds'])))

    def start(self):
        if sum(t['active'] for t in self.data['teams']) < 2:
            return False
        if not self.data['running']:
            self.data['deadline'] = time.time() + max(1, self.remaining())
            self.data['running'] = True
            self.event('start', '⚽ ¡ARRANCA EL PARTIDO!')
            self.save()
        return True

    def pause(self):
        self.data['remaining'] = self.remaining()
        self.data['running'] = False
        self.event('pause', '⏸ PARTIDO EN PAUSA')
        self.save()

    def reset(self):
        for t in self.data['teams']:
            t['points'], t['active'] = 0, True
        self.data['running'] = False
        self.data['remaining'] = int(self.data['settings']['seconds'])
        self.event('reset', '🔄 NUEVO CAMPEONATO')
        self.save()

    def eliminate(self):
        alive = [t for t in self.data['teams'] if t['active']]
        if len(alive) <= 1:
            self.data['running'] = False
            return
        loser = min(alive, key=lambda t: (t['points'], t['name']))
        loser['active'] = False
        self.event('elimination', '❌ ELIMINADO: ' + loser['name'])
        if len(alive) == 2:
            self.data['running'] = False
            winner = next(t for t in self.data['teams'] if t['active'])
            self.event('champion', '🏆 CAMPEÓN: ' + winner['name'])
        else:
            seconds = max(10, int(self.data['settings']['seconds']))
            self.data['remaining'] = seconds
            if self.data['running']:
                self.data['deadline'] = time.time() + seconds
        self.save()

    def add_gift(self, index, count=1, gift_name=None):
        if not (0 <= index < len(self.data['teams'])):
            return False
        t = self.data['teams'][index]
        if not t['active'] or (gift_name is not None and t['gift'].casefold() != gift_name.casefold()):
            return False
        count = min(9999, max(1, int(count)))
        pts = max(0, int(t['value'])) * count
        t['points'] += pts
        self.event('goal', f'⚽ ¡GOOOL! {t["name"]} +{pts}')
        self.save()
        return True

    def match_live_gift(self, gift, count):
        matches = [i for i, t in enumerate(self.data['teams'])
                   if t['active'] and t['gift'].strip().casefold() == gift.strip().casefold()]
        if len(matches) != 1:
            return False
        return self.add_gift(matches[0], count, gift)

class LeagueWorker(QThread):
    success = Signal(list, str)
    failed = Signal(str)
    leagues = Signal(list)
    def __init__(self, settings, search=False):
        super().__init__()
        self.settings = copy.deepcopy(settings)
        self.search = search

    def run(self):
        try:
            s = self.settings
            if not s['api_key']:
                raise ValueError('Falta la clave de API-Football')
            if not self.search and not s['league_id']:
                raise ValueError('Falta el ID de liga')
            if self.search:
                url = 'https://v3.football.api-sports.io/leagues?country=Colombia'
            else:
                args = urllib.parse.urlencode({'league': s['league_id'], 'season': s['season']})
                url = 'https://v3.football.api-sports.io/standings?' + args
            req = urllib.request.Request(url, headers={'x-apisports-key': s['api_key'],
                                                        'User-Agent': 'FutbolLivePro/2.0'})
            with urllib.request.urlopen(req, timeout=20) as response:
                result = json.load(response)
            if result.get('errors'):
                raise ValueError(str(result['errors']))
            if self.search:
                entries = [{'id': r['league']['id'], 'name': r['league']['name']}
                           for r in result.get('response', [])]
                self.leagues.emit(entries)
                return
            entries = result.get('response', [])
            if not entries:
                raise ValueError('Sin clasificación para liga y temporada seleccionadas')
            groups = entries[0].get('league', {}).get('standings', [])
            rows = []
            for group in groups:
                for r in group:
                    team, a = r.get('team', {}), r.get('all', {})
                    goals = a.get('goals', {})
                    rows.append({'rank': r.get('rank', 0), 'name': team.get('name', ''),
                      'logo': team.get('logo', ''), 'played': a.get('played', 0),
                      'win': a.get('win', 0), 'draw': a.get('draw', 0),
                      'lose': a.get('lose', 0), 'gf': goals.get('for', 0),
                      'ga': goals.get('against', 0), 'gd': r.get('goalsDiff', 0),
                      'points': r.get('points', 0), 'group': r.get('group', '')})
            if not rows:
                raise ValueError('El proveedor no entregó filas de clasificación')
            self.success.emit(rows, time.strftime('%Y-%m-%d %H:%M:%S'))
        except Exception as exc:
            self.failed.emit(str(exc))

class TikTokWorker(QThread):
    gift = Signal(str, int)
    status = Signal(str)
    def __init__(self, username):
        super().__init__()
        self.username = username.strip().lstrip('@')
        self.loop = None
        self.client = None

    def run(self):
        try:
            from TikTokLive import TikTokLiveClient
            from TikTokLive.events import GiftEvent
        except ImportError:
            self.status.emit('TikTokLive no está instalado en este ejecutable')
            return
        async def connect():
            self.loop = asyncio.get_running_loop()
            self.client = TikTokLiveClient(unique_id='@' + self.username)
            @self.client.on(GiftEvent)
            async def received(event):
                try:
                    gift = str(event.gift.name)
                    if getattr(event.gift, 'streakable', False) and not getattr(event, 'repeat_end', True):
                        return
                    count = max(1, int(getattr(event, 'repeat_count', 1)))
                    self.gift.emit(gift, count)
                except Exception as exc:
                    self.status.emit('Error en regalo: ' + str(exc))
            self.status.emit('Conectando con @' + self.username + '...')
            await self.client.start()
        try:
            asyncio.run(connect())
        except Exception as exc:
            self.status.emit('TikTok desconectado: ' + str(exc))
        finally:
            self.loop = None
            self.client = None

    def disconnect_live(self):
        if self.loop and self.client and self.loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self.client.disconnect(), self.loop)
            except Exception as exc:
                self.status.emit(str(exc))

class ImageCache(QWidget):
    """Caché de escudos con descargas asíncronas Qt; no bloquea la ventana."""
    changed = Signal()
    def __init__(self):
        super().__init__()
        self.manager = QNetworkAccessManager(self)
        self.pixmaps = {}
        self.pending = set()

    def get(self, path):
        if not path:
            return None
        if path in self.pixmaps:
            return self.pixmaps[path]
        if path in self.pending:
            return None
        if path.startswith(('http://', 'https://')):
            self.pending.add(path)
            reply = self.manager.get(QNetworkRequest(QUrl(path)))
            def finish():
                pm = QPixmap()
                if reply.error() == reply.NetworkError.NoError:
                    pm.loadFromData(reply.readAll())
                self.pixmaps[path] = pm if not pm.isNull() else None
                self.pending.discard(path)
                reply.deleteLater()
                self.changed.emit()
            reply.finished.connect(finish)
            return None
        pm = QPixmap(path)
        self.pixmaps[path] = pm if not pm.isNull() else None
        return self.pixmaps[path]

class StadiumWindow(QWidget):
    def __init__(self, store, cache, title, kind='battle', stadium=True):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.store, self.cache, self.kind, self.stadium = store, cache, kind, stadium
        self.chroma = False
        self.transparent = False
        self.setWindowTitle(title)
        self.resize(540, 960)
        self.setMinimumSize(320, 568)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.store.listeners.append(self.update)
        self.cache.changed.connect(self.update)
        self.alert_until = 0
        self.last_ts = store.data['event'].get('ts', 0)
        self.anim = QTimer(self)
        self.anim.timeout.connect(self.update)
        self.anim.start(100)

    def set_background(self, mode):
        self.transparent = mode == 'transparent'
        self.chroma = mode == 'chroma'
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        elif event.key() == Qt.Key.Key_F11:
            self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        sx, sy = w / 540, h / 960
        p.scale(sx, sy)
        if self.chroma:
            p.fillRect(QRect(0, 0, 540, 960), QColor('#00ff00'))
        elif not self.transparent:
            grad = QLinearGradient(270, 0, 270, 960)
            grad.setColorAt(0, QColor('#03110e'))
            grad.setColorAt(.57, QColor('#103e2b'))
            grad.setColorAt(1, QColor('#062016'))
            p.fillRect(QRect(0, 0, 540, 960), grad)
            p.setPen(QPen(QColor(255, 255, 255, 13), 2))
            for y in range(0, 960, 80):
                p.drawLine(0, y, 540, y)
            p.setPen(QPen(QColor('#366b4c'), 3))
            p.drawEllipse(QRect(65, 650, 410, 200))
            p.drawLine(270, 640, 270, 940)
        self.roundrect(p, QRect(12, 14, 516, 110), '#0a271f', '#e6c06d', 16)
        self.text(p, QRect(20, 23, 500, 22), 'ESTADIO LEGENDARIO · COLOMBIA', 13, '#81e6b2', True)
        self.text(p, QRect(20, 46, 500, 45), 'FÚTBOL LIVE PRO', 32, '#f9d47f', True)
        self.text(p, QRect(20, 93, 500, 22), '⚽ BATALLA DE HINCHADAS ⚽' if self.kind == 'battle' else '🏆 LIGA BETPLAY · CLASIFICACIÓN', 13, '#a7e8c2', True)
        if self.kind == 'battle':
            self.draw_battle(p)
        else:
            self.draw_league(p)
        ev = self.store.data.get('event', {})
        if self.kind == 'battle' and ev.get('ts', 0) != self.last_ts:
            self.last_ts = ev.get('ts', 0)
            self.alert_until = time.time() + 3.5
        if self.kind == 'battle' and time.time() < self.alert_until:
            self.roundrect(p, QRect(24, 414, 492, 128), '#0b2b20', '#ffd26d', 18)
            self.text(p, QRect(34, 428, 472, 98), ev.get('text', ''), 23, '#ffe2a1', True)
        self.text(p, QRect(12, 922, 516, 22), '🏆 SOLO UNA HINCHADA CONQUISTARÁ EL ESTADIO 🏆', 10, '#a8e1bd', True)
        p.end()

    @staticmethod
    def text(p, rect, txt, size, color, bold=False, align=Qt.AlignmentFlag.AlignCenter):
        font = QFont('Segoe UI', size)
        font.setBold(bold)
        p.setFont(font)
        p.setPen(QColor(color))
        p.drawText(rect, align | Qt.TextFlag.TextWordWrap, str(txt))

    @staticmethod
    def roundrect(p, rect, bg, border, radius=12):
        p.setBrush(QBrush(QColor(bg)))
        p.setPen(QPen(QColor(border), 1.4))
        p.drawRoundedRect(rect, radius, radius)

    def draw_battle(self, p):
        d = self.store.data
        sec = self.store.remaining()
        alive = [t for t in d['teams'] if t['active']]
        self.roundrect(p, QRect(16, 136, 124, 48), '#081b15', '#d4ae62')
        self.text(p, QRect(18, 141, 120, 38), f'{sec//60:02}:{sec%60:02}', 24, '#ffd77a', True)
        self.text(p, QRect(145, 138, 245, 44), '🔴 EN VIVO' if d['running'] else '⏸ EN ESPERA', 16, '#a5efc5', True)
        self.roundrect(p, QRect(395, 136, 130, 48), '#081b15', '#d4ae62')
        self.text(p, QRect(398, 142, 125, 38), f'{len(alive)} CLUBES', 14, '#ffd77a', True)
        sorted_teams = self.store.sorted_teams()
        danger = min((t['points'] for t in alive), default=-1)
        for i, t in enumerate(sorted_teams):
            y = 195 + i * 35
            if y > 900:
                break
            is_leader = i == 0 and t['active']
            is_danger = t['active'] and t['points'] == danger and len(alive) > 1
            bg = '#51401f' if is_leader else '#402023' if is_danger else '#103629'
            border = '#f8d279' if is_leader else '#e27370' if is_danger else '#3d7558'
            self.roundrect(p, QRect(16, y, 508, 32), bg, border, 7)
            if not t['active']:
                p.fillRect(QRect(17, y+1, 506, 30), QColor(0, 0, 0, 150))
            self.text(p, QRect(21, y+2, 30, 28), '👑' if is_leader else str(i+1), 11, '#f9d581', True)
            logo = self.cache.get(t.get('logo', ''))
            if logo:
                p.drawPixmap(QRect(52, y+2, 28, 28), logo)
            else:
                self.text(p, QRect(52, y+1, 28, 30), '◆', 13, '#a4d4b3', True)
            name = t['name']
            if len(name) > 23:
                name = name[:22] + '…'
            self.text(p, QRect(83, y+1, 292, 18), name, 11, '#f5fff7', True, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.text(p, QRect(83, y+18, 290, 13), f"🎁 {t['gift']} · +{t['value']}", 8, '#9bd2b3', False, Qt.AlignmentFlag.AlignLeft)
            self.text(p, QRect(384, y+1, 126, 30), str(t['points']), 16, '#ffda80', True, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def draw_league(self, p):
        d = self.store.data
        self.text(p, QRect(15, 136, 510, 35),
                  'Datos: ' + (d['league_updated'] or 'Sin sincronizar'), 12, '#a6edc6', True)
        self.roundrect(p, QRect(15, 174, 510, 33), '#1c4b36', '#e2bb6b', 6)
        self.text(p, QRect(25, 175, 500, 30), 'POS     CLUB                                         PJ       DG      PTS', 11, '#f8d47b', True)
        rows = d['league']
        if not rows:
            self.text(p, QRect(35, 300, 470, 170), 'Sin clasificación sincronizada.\nConfigura API-Football desde el panel.', 17, '#ffffff', True)
            return
        for i, r in enumerate(rows[:20]):
            y = 213 + i*34
            if y > 906:
                break
            self.roundrect(p, QRect(15, y, 510, 31), '#244b32' if self.stadium else '#182b29', '#ac8e4d' if i == 0 else '#42745a', 5)
            self.text(p, QRect(18, y, 34, 30), str(r.get('rank', i+1)), 12, '#f6cf72', True)
            logo = self.cache.get(r.get('logo', ''))
            if logo:
                p.drawPixmap(QRect(55, y+2, 27, 27), logo)
            name = r.get('name', '')
            self.text(p, QRect(86, y+1, 267, 29), name[:28], 11, '#ffffff', True, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            for x, field in ((365, 'played'), (414, 'gd'), (471, 'points')):
                self.text(p, QRect(x, y, 40, 30), str(r.get(field, 0)), 12, '#ffdc84', True)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.store = Store()
        self.cache = ImageCache()
        self.cache.changed.connect(self.render)
        self.workers = []
        self.tiktok = None
        self.last_sync = 0
        self.setWindowTitle('FÚTBOL LIVE PRO 2026 · ESTADIO LEGENDARIO')
        self.resize(1370, 860)
        self.setMinimumSize(960, 620)
        self.windows = {
            'legend': StadiumWindow(self.store, self.cache, 'Estadio Legendario', 'battle', True),
            'classic': StadiumWindow(self.store, self.cache, 'Liga BetPlay · Tabla Tradicional', 'league', False),
            'stadium': StadiumWindow(self.store, self.cache, 'Liga BetPlay · Estadio', 'league', True),
        }
        self.build_ui()
        self.store.listeners.append(self.render)
        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self.tick)
        self.tick_timer.start(250)
        self.render()

    def button(self, text, fn):
        b = QPushButton(text)
        b.clicked.connect(fn)
        return b

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        heading = QLabel('🏟  FÚTBOL LIVE PRO 2026   ·   ESTADIO LEGENDARIO')
        heading.setObjectName('heading')
        outer.addWidget(heading)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)
        control = QWidget()
        self.tabs.addTab(control, '⚽ Batalla de hinchadas')
        v = QVBoxLayout(control)
        actions = QHBoxLayout()
        for label, fn in [('▶ Iniciar', self.start), ('⏸ Pausar', self.store.pause),
                          ('❌ Eliminar último', self.store.eliminate), ('↺ Reiniciar', self.reset),
                          ('🎁 Simular regalo', self.simulate), ('+🎁 Regalo manual', self.simulate)]:
            actions.addWidget(self.button(label, fn))
        v.addLayout(actions)
        self.timer_label = QLabel('03:00')
        self.timer_label.setObjectName('clock')
        self.event_label = QLabel('Preparando estadio')
        v.addWidget(self.timer_label)
        v.addWidget(self.event_label)
        self.teams_table = QTableWidget(20, 7)
        self.teams_table.setHorizontalHeaderLabels(['#', 'Equipo', 'Puntos', 'Regalo', 'Valor', 'URL escudo', 'Estado'])
        self.teams_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.teams_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.teams_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.teams_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        v.addWidget(self.teams_table)
        edit = QGroupBox('Editar equipo seleccionado')
        form = QGridLayout(edit)
        self.team_select = QComboBox()
        self.team_select.addItems(t['name'] for t in self.store.data['teams'])
        self.team_select.currentIndexChanged.connect(self.load_team)
        self.team_name = QLineEdit()
        self.team_gift = QLineEdit()
        self.team_value = QSpinBox(); self.team_value.setRange(0, 10000000)
        self.team_points = QSpinBox(); self.team_points.setRange(0, 1000000000)
        self.team_logo = QLineEdit()
        self.team_active = QCheckBox('Activo')
        fields = [('Equipo', self.team_select), ('Nombre', self.team_name), ('Regalo', self.team_gift),
                  ('Puntos por regalo', self.team_value), ('Puntos actuales', self.team_points),
                  ('Escudo (URL o archivo)', self.team_logo), ('Participa', self.team_active)]
        for i, (label, widget) in enumerate(fields):
            form.addWidget(QLabel(label), i // 4, (i % 4) * 2)
            form.addWidget(widget, i // 4, (i % 4) * 2 + 1)
        form.addWidget(self.button('💾 Guardar equipo', self.save_team), 2, 0, 1, 8)
        v.addWidget(edit)
        overlay_tab = QWidget()
        self.tabs.addTab(overlay_tab, '📺 Ventanas para LIVE Studio')
        ol = QVBoxLayout(overlay_tab)
        ol.addWidget(QLabel('Las ventanas son NATIVAS. En TikTok LIVE Studio usa «Captura de ventana».\n'
                            'La resolución inicial es 540 × 960 (9:16). Puedes redimensionar o maximizar con F11.'))
        for key, title in [('legend', '🏟 Abrir estadio legendario'), ('classic', '📊 Abrir tabla tradicional'),
                           ('stadium', '🏆 Abrir tabla estadio')]:
            ol.addWidget(self.button(title, lambda _, k=key: self.show_overlay(k)))
        ol.addWidget(QLabel('Fondo del estadio:'))
        self.bg_combo = QComboBox()
        self.bg_combo.addItems(['Estadio', 'Transparente', 'Verde chroma'])
        self.bg_combo.currentIndexChanged.connect(self.change_background)
        ol.addWidget(self.bg_combo)
        ol.addWidget(QLabel('ESC oculta una ventana de overlay. F11 alterna pantalla completa.'))
        ol.addStretch()
        league_tab = QWidget()
        self.tabs.addTab(league_tab, '🇨🇴 Liga BetPlay')
        ll = QVBoxLayout(league_tab)
        self.league_status = QLabel('Sin sincronizar')
        ll.addWidget(self.league_status)
        ll.addWidget(self.button('🔄 Actualizar clasificación ahora', self.update_league))
        self.league_table = QTableWidget(0, 9)
        self.league_table.setHorizontalHeaderLabels(['Pos', 'Club', 'PJ', 'G', 'E', 'P', 'GF', 'DG', 'PTS'])
        self.league_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.league_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        ll.addWidget(self.league_table)
        settings_tab = QWidget()
        self.tabs.addTab(settings_tab, '⚙️ Configuración')
        sv = QVBoxLayout(settings_tab)
        s = self.store.data['settings']
        form = QFormLayout()
        self.seconds = QSpinBox(); self.seconds.setRange(10, 86400); self.seconds.setValue(int(s['seconds']))
        self.mode = QComboBox(); self.mode.addItem('El último queda eliminado', 'elimination'); self.mode.addItem('Batalla sin eliminación', 'battle')
        self.mode.setCurrentIndex(0 if s['mode'] == 'elimination' else 1)
        self.api_key = QLineEdit(str(s['api_key'])); self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.league_id = QLineEdit(str(s['league_id']))
        self.season = QSpinBox(); self.season.setRange(2000, 2100); self.season.setValue(int(s['season']))
        self.refresh = QComboBox(); self.refresh.addItems(['15', '30', '60']); self.refresh.setCurrentText(str(s['refresh']))
        self.username = QLineEdit(str(s['live_user']))
        for label, widget in [('Eliminar cada (segundos)', self.seconds), ('Modo', self.mode),
                              ('API-Football key', self.api_key), ('ID de liga', self.league_id),
                              ('Temporada', self.season), ('Sincronización (minutos)', self.refresh),
                              ('Usuario TikTok (sin @)', self.username)]:
            form.addRow(label, widget)
        sv.addLayout(form)
        sv.addWidget(self.button('💾 Guardar configuración', self.save_settings))
        sv.addWidget(self.button('🔎 Buscar ligas de Colombia', self.search_leagues))
        self.league_select = QComboBox()
        sv.addWidget(self.league_select)
        sv.addWidget(self.button('Usar liga seleccionada', self.select_league))
        sv.addWidget(QLabel('La tabla oficial depende de API-Football; verifica la fase del Finalización 2026.'))
        sv.addStretch()
        tiktok_tab = QWidget()
        self.tabs.addTab(tiktok_tab, '🎁 TikTok LIVE')
        tv = QVBoxLayout(tiktok_tab)
        self.tiktok_status = QLabel('Desconectado · Conector no oficial, requiere LIVE activo')
        tv.addWidget(self.tiktok_status)
        tv.addWidget(self.button('🔗 Conectar a TikTok LIVE', self.connect_tiktok))
        tv.addWidget(self.button('⛔ Desconectar', self.disconnect_tiktok))
        tv.addWidget(QLabel('Solo se suman regalos con una asignación ÚNICA entre equipos activos.\n'
                            'El valor de cada regalo se define en la pestaña Batalla.\n'
                            'Los regalos de racha se contabilizan al finalizar la racha.'))
        tv.addStretch()
        self.setStyleSheet('''
            QWidget {background:#071811; color:#e6f9ed; font: 12px 'Segoe UI';}
            QMainWindow {background:#06150e;} #heading {background:#133b2a; color:#f8d47d;
                font-size:21px; font-weight:bold; padding:15px; border-bottom:2px solid #d3a954;}
            QTabWidget::pane, QGroupBox {border:1px solid #3b7958; border-radius:8px;}
            QTabBar::tab {background:#143827; padding:11px 18px; margin-right:2px;}
            QTabBar::tab:selected {background:#bc933e; color:#06160d; font-weight:bold;}
            QPushButton {background:#bc933e; color:#09190e; font-weight:bold;
                border:1px solid #e5c371; padding:9px; border-radius:6px;}
            QPushButton:hover {background:#f4d680;}
            QLineEdit, QSpinBox, QComboBox {background:#112d21; border:1px solid #47775c;
                padding:6px; border-radius:5px;}
            QTableWidget {background:#10291d; alternate-background-color:#173a2b;
                gridline-color:#2c5741; selection-background-color:#7a632e;}
            QHeaderView::section {background:#204a32; color:#f8d47d; padding:7px;}
            #clock {font-size:32px; color:#f9cf71; font-weight:bold;}
            QLabel {padding:3px;} QGroupBox {margin-top:7px; padding:9px;}
        ''')
        self.load_team()

    def show_overlay(self, key):
        win = self.windows[key]
        win.show()
        win.raise_()
        win.activateWindow()

    def change_background(self, index):
        mode = ['stadium', 'transparent', 'chroma'][index]
        self.windows['legend'].set_background(mode)

    def load_team(self, *_):
        i = self.team_select.currentIndex()
        if i < 0:
            return
        t = self.store.data['teams'][i]
        self.team_name.setText(t['name'])
        self.team_gift.setText(t['gift'])
        self.team_value.setValue(int(t['value']))
        self.team_points.setValue(int(t['points']))
        self.team_logo.setText(t.get('logo', ''))
        self.team_active.setChecked(bool(t['active']))

    def save_team(self):
        i = self.team_select.currentIndex()
        if i < 0:
            return
        t = self.store.data['teams'][i]
        t.update(name=self.team_name.text().strip() or t['name'], gift=self.team_gift.text().strip(),
                 value=self.team_value.value(), points=self.team_points.value(),
                 logo=self.team_logo.text().strip(), active=self.team_active.isChecked())
        self.team_select.setItemText(i, t['name'])
        self.store.save()

    def simulate(self):
        self.store.add_gift(self.team_select.currentIndex())

    def start(self):
        if not self.store.start():
            QMessageBox.information(self, 'Campeonato', 'Reinicia el torneo: quedan menos de dos equipos activos.')

    def reset(self):
        if QMessageBox.question(self, 'Reiniciar', '¿Borrar puntos y reactivar todos los equipos?') == QMessageBox.StandardButton.Yes:
            self.store.reset()
            self.load_team()

    def save_settings(self):
        s = self.store.data['settings']
        s.update(seconds=self.seconds.value(), mode=self.mode.currentData(), api_key=self.api_key.text().strip(),
                 league_id=self.league_id.text().strip(), season=self.season.value(),
                 refresh=int(self.refresh.currentText()), live_user=self.username.text().strip().lstrip('@'))
        if not self.store.data['running']:
            self.store.data['remaining'] = s['seconds']
        self.store.save()
        self.statusBar().showMessage('Configuración guardada', 3000)

    def worker(self, search=False):
        self.save_settings()
        worker = LeagueWorker(self.store.data['settings'], search)
        self.workers.append(worker)
        worker.finished.connect(lambda: self.workers.remove(worker) if worker in self.workers else None)
        worker.failed.connect(self.league_error)
        worker.success.connect(self.league_success)
        worker.leagues.connect(self.leagues_found)
        worker.start()
        self.last_sync = time.time()

    def update_league(self):
        self.league_status.setText('Consultando proveedor deportivo...')
        self.worker()

    def search_leagues(self):
        self.worker(True)

    def league_success(self, rows, stamp):
        d = self.store.data
        d['league'], d['league_updated'], d['league_error'] = rows, stamp, ''
        self.store.save()

    def league_error(self, msg):
        self.store.data['league_error'] = msg
        self.store.save()

    def leagues_found(self, rows):
        self.league_select.clear()
        for row in rows:
            self.league_select.addItem(f"{row['name']} (ID {row['id']})", str(row['id']))
        self.statusBar().showMessage(f'{len(rows)} competiciones encontradas', 5000)

    def select_league(self):
        if self.league_select.currentData():
            self.league_id.setText(self.league_select.currentData())
            self.save_settings()

    def connect_tiktok(self):
        self.save_settings()
        user = self.store.data['settings']['live_user']
        if not user:
            QMessageBox.warning(self, 'TikTok', 'Escribe tu usuario en Configuración.')
            return
        if self.tiktok and self.tiktok.isRunning():
            return
        self.tiktok = TikTokWorker(user)
        self.tiktok.gift.connect(self.on_live_gift)
        self.tiktok.status.connect(self.tiktok_status.setText)
        self.tiktok.finished.connect(lambda: self.tiktok_status.setText('TikTok desconectado'))
        self.tiktok.start()

    def on_live_gift(self, gift, count):
        if self.store.match_live_gift(gift, count):
            self.tiktok_status.setText(f'🎁 {gift} ×{count} registrado')
        else:
            self.tiktok_status.setText(f'⚠️ {gift}: sin equipo único asignado')

    def disconnect_tiktok(self):
        if self.tiktok:
            self.tiktok.disconnect_live()

    def tick(self):
        if self.store.data['running'] and self.store.data['settings']['mode'] == 'elimination' and self.store.remaining() <= 0:
            self.store.eliminate()
        seconds = self.store.remaining()
        self.timer_label.setText(f'⏱ {seconds//60:02}:{seconds%60:02}' + ('  🔴 EN VIVO' if self.store.data['running'] else '  ⏸ PAUSA'))
        s = self.store.data['settings']
        if s.get('api_key') and s.get('league_id') and not self.workers and time.time()-self.last_sync >= int(s['refresh'])*60:
            self.worker()

    def render(self):
        d = self.store.data
        self.event_label.setText(d['event']['text'])
        self.teams_table.setRowCount(len(d['teams']))
        for i, t in enumerate(self.store.sorted_teams()):
            vals = [str(i+1), t['name'], str(t['points']), t['gift'], str(t['value']), t.get('logo', ''), 'ACTIVO' if t['active'] else 'ELIMINADO']
            for j, value in enumerate(vals):
                item = QTableWidgetItem(value)
                if not t['active']:
                    item.setForeground(QColor('#839489'))
                elif i == 0:
                    item.setForeground(QColor('#ffda7a'))
                self.teams_table.setItem(i, j, item)
        self.league_table.setRowCount(len(d['league']))
        for i, r in enumerate(d['league']):
            vals = [r.get('rank', i+1), r.get('name', ''), r.get('played', 0), r.get('win', 0),
                    r.get('draw', 0), r.get('lose', 0), r.get('gf', 0), r.get('gd', 0), r.get('points', 0)]
            for j, val in enumerate(vals):
                item = QTableWidgetItem(str(val))
                if j == 1:
                    pm = self.cache.get(r.get('logo', ''))
                    if pm:
                        from PySide6.QtGui import QIcon
                        item.setIcon(QIcon(pm))
                self.league_table.setItem(i, j, item)
        self.league_status.setText((d['league_updated'] or 'Sin sincronizar') + ' · ' + (d['league_error'] or 'Datos recibidos del proveedor'))

    def closeEvent(self, event):
        if self.tiktok:
            self.tiktok.disconnect_live()
        self.store.data['remaining'] = self.store.remaining()
        self.store.data['running'] = False
        self.store.save()
        for win in self.windows.values():
            win.close()
        super().closeEvent(event)

def main():
    app = QApplication(sys.argv)
    app.setApplicationName('FutbolLivePro')
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
