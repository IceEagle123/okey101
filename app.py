from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room
import random
import threading
import time
import itertools
import uuid
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'okey_pro_secret_999'
# Profesyonel yapı için threading modunda çalıştırıyoruz
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# TÜM OYUN VERİLERİNİN TUTULDUĞU MERKEZ (HİÇBİR ŞEY ATLANMADI)
oyun_merkezi = {
    'deste': [],
    'atilan_taslar': [],
    'oyuncular': {},      # sid: { el: [], acilan_seriler: [], puan: 0 }
    'masa_serileri': [],  # Herkesin görebileceği yere açılmış perler
    'gosterge': None,     # Masadaki gösterge taşı
    'okey': None,         # Okey olan taş (Gösterge + 1)
    'sira': 0,            # Sıranın kimde olduğu (0-3 arası index)
    'baslayan': 0,        # Bu tur kimin başladığı
    'tur_id': 0,          # Tur takibi için sayaç
    'koltuklar': [None] * 4 # 4 Sabit Koltuk (0, 1, 2, 3)
}

TUR_SAYISI = 0 # Global tur sayacı

def deste_olustur():
    """106 taşlık tam 101 okey destesi oluşturur."""
    renkler = ['red', 'black', 'blue', 'orange']
    deste = []
    # Her renkten 1-13 arası ikişer adet
    for r in renkler:
        for s in range(1, 14):
            deste.append({'renk': r, 'sayi': s})
            deste.append({'renk': r, 'sayi': s})
    # 2 Adet Sahte Okey (Joker)
    deste.extend([{'renk': 'black', 'sayi': 0}, {'renk': 'black', 'sayi': 0}])
    random.shuffle(deste)
    return deste

def okey_hesapla(gosterge):
    """Göstergeye göre okey taşını belirler."""
    okey_sayi = gosterge['sayi'] + 1
    if okey_sayi > 13: okey_sayi = 1
    return {'renk': gosterge['renk'], 'sayi': okey_sayi}

def get_unique_name(base_name):
    """İsmin benzersiz olmasını sağlar (Ahmet -> Ahmet_123)."""
    base_name = base_name.strip()
    if not base_name: base_name = "Misafir"
    
    existing = {p['isim'].lower() for p in oyun_merkezi['oyuncular'].values()}
    
    if base_name.lower() not in existing:
        return base_name
    
    while True:
        suffix = random.randint(100, 999)
        new_name = f"{base_name}_{suffix}"
        if new_name.lower() not in existing:
            return new_name

def broadcast_oyuncular():
    """Oyuncu listesini ve taş sayılarını herkese gönderir."""
    liste = []
    for sid, p in oyun_merkezi['oyuncular'].items():
        liste.append({
            'sid': sid, # Admin işlemleri için ID gerekli
            'isim': p['isim'], 
            'tas_sayisi': len(p['el']), 
            'puan': p['puan'],
            'is_bot': p.get('is_bot', False),
            'koltuk': p.get('koltuk', -1),
            'takim': p.get('takim', '?')
        })
    emit('oyuncular_guncelle', liste, room='masa1')

def bot_hamle_yap(hedef_tur_id):
    """Bot hamlesini güvenli bir şekilde yapar."""
    with app.app_context():
        # Eğer tur değişmişse (örneğin araya biri girdiyse veya oyun bittiyse) iptal et
        if oyun_merkezi['tur_id'] != hedef_tur_id:
            return
        otomatik_hamle()

def check_bot_turn():
    """Sıradaki oyuncu bot ise otomatik hamleyi tetikler."""
    # Koltuk sistemine göre sıradaki oyuncuyu bul
    aktif_sid = oyun_merkezi['koltuklar'][oyun_merkezi['sira']]
    if not aktif_sid: return # Koltuk boşsa işlem yapma

    player = oyun_merkezi['oyuncular'][aktif_sid]
    
    if player.get('is_bot', False):
        # Bot ise 3 saniye sonra hamle yapması için zamanlayıcıyı tetikle
        # (Otomatik hamle fonksiyonu bot mantığını da içerir)
        threading.Timer(3.0, otomatik_hamle).start()
        # Bot ise 1.5 saniye sonra hamle yap (Hızlandırıldı ve Güvenli Hale Getirildi)
        threading.Timer(1.5, bot_hamle_yap, args=[oyun_merkezi['tur_id']]).start()

def zamanlayici_baslat(tur_id):
    """60 saniye bekler ve hamle yapılmadıysa otomatik oynar."""
    time.sleep(60)
    with app.app_context():
        if oyun_merkezi['tur_id'] == tur_id:
            otomatik_hamle()

def otomatik_hamle():
    """Sırası gelen oyuncu oynamadıysa yerine oynar."""
    aktif_sid = oyun_merkezi['koltuklar'][oyun_merkezi['sira']]
    if not aktif_sid: return

    player = oyun_merkezi['oyuncular'][aktif_sid]
    
    # 1. Taş Çek (Eğer 21 taşı varsa)
    if len(player['el']) < 22:
        if oyun_merkezi['deste']:
            yeni_tas = oyun_merkezi['deste'].pop()
        else:
            oyun_merkezi['deste'] = deste_olustur()
            yeni_tas = oyun_merkezi['deste'].pop()
        player['el'].append(yeni_tas)
        socketio.emit('yeni_tas_geldi', yeni_tas, room=aktif_sid)
    
    # 2. Rastgele Taş At
    if player['el']:
        atilacak = random.choice(player['el'])
        player['el'].remove(atilacak)
        oyun_merkezi['atilan_taslar'].append(atilacak)
        
        socketio.emit('taslari_al', {'taslar': player['el']}, room=aktif_sid)
        socketio.emit('yeni_tas_atildi', atilacak, room='masa1')
        
    # 3. Sırayı Geçir ve Yeni Tur Başlat
    oyun_merkezi['sira'] = (oyun_merkezi['sira'] + 1) % 4
        
    oyun_merkezi['tur_id'] += 1
    aktif_sid = oyun_merkezi['koltuklar'][oyun_merkezi['sira']]
    socketio.emit('sira_bilgisi', {'sira': oyun_merkezi['sira'], 'baslayan': oyun_merkezi['baslayan'], 'sure': 60, 'aktif_sid': aktif_sid}, room='masa1')
    broadcast_oyuncular()
    
    # Eğer sıradaki oyuncu bot ise tetikle
    check_bot_turn()
    
    threading.Thread(target=zamanlayici_baslat, args=(oyun_merkezi['tur_id'],)).start()

def validate_hand_structure(taslar, okey_tas):
    """Seçilen taşların geçerli perlerden (1-2-3 veya 7-7-7) oluşup oluşmadığını kontrol eder."""
    jokers = 0
    regulars = []
    for t in taslar:
        s = int(t['sayi'])
        r = t['renk']
        # Okey (Joker) Kontrolü
        if s == okey_tas['sayi'] and r == okey_tas['renk']:
            jokers += 1
        # Sahte Okey Kontrolü (0 -> Okey'in değeri)
        elif s == 0:
            regulars.append({'renk': okey_tas['renk'], 'sayi': okey_tas['sayi']})
        else:
            regulars.append({'renk': r, 'sayi': s})
            
    return _solve_partition(regulars, jokers)

def _solve_partition(tiles, jokers):
    """Recursive backtracking ile taşları geçerli setlere ayırmaya çalışır."""
    if not tiles:
        # Tüm normal taşlar kullanıldı. Eğer joker kaldıysa bu geçersizdir (fazla joker).
        # Kullanıcı seçtiği taşları açtığı için hepsini kullanmak zorundadır.
        if jokers == 0:
            return True, 0
        else:
            return False, 0
        
    root = tiles[0]
    remaining = tiles[1:]
    
    # 1. GRUP DENEMESİ (Aynı Sayı, Farklı Renk) - Örn: Kırmızı 7, Siyah 7, Mavi 7
    candidates = [t for t in remaining if t['sayi'] == root['sayi'] and t['renk'] != root['renk']]
    
    # Renklere göre grupla (Aynı renkten 2 tane varsa sadece birini kullanabiliriz)
    cand_by_color = {}
    for c in candidates:
        if c['renk'] not in cand_by_color: cand_by_color[c['renk']] = []
        cand_by_color[c['renk']].append(c)
    distinct_colors = list(cand_by_color.keys())
    
    # 3'lü ve 4'lü grupları dene
    for size in [3, 4]:
        needed = size - 1
        for j in range(min(needed, jokers) + 1): # j tane joker kullan
            from_cands = needed - j
            if from_cands == 0: # Sadece jokerlerle tamamla
                valid, rest_score = _solve_partition(remaining, jokers - j)
                if valid:
                    # Grup puanı: Sayı * Adet (Jokerler de sayı değerini alır)
                    current_score = root['sayi'] * size
                    return True, current_score + rest_score
            else:
                # Farklı renk kombinasyonlarını dene
                for combo_colors in itertools.combinations(distinct_colors, from_cands):
                    temp_remaining = list(remaining)
                    valid_combo = True
                    for color in combo_colors:
                        found = False
                        for idx, t in enumerate(temp_remaining):
                            if t['sayi'] == root['sayi'] and t['renk'] == color:
                                temp_remaining.pop(idx)
                                found = True
                                break
                        if not found: valid_combo = False; break
                    
                    if valid_combo:
                        valid, rest_score = _solve_partition(temp_remaining, jokers - j)
                        if valid:
                            current_score = root['sayi'] * size
                            return True, current_score + rest_score

    # 2. SERİ DENEMESİ (Aynı Renk, Ardışık Sayı) - Örn: Kırmızı 1-2-3
    root_val = root['sayi']
    # Olası serileri dene (Maksimum 13 uzunluk)
    for length in range(3, 14):
        # Root'u içeren tüm olası başlangıç değerlerini dene (1..13)
        # Bu sayede 12-13-1 gibi serilerde root 1 olsa bile doğru bulunur.
        for start_val in range(1, 14):
            sequence = []
            valid_seq = True
            for k in range(length):
                val = start_val + k
                real_val = val
                if val == 14: real_val = 1 # 12-13-1 desteği
                if val > 14 or val < 1: valid_seq = False; break
                sequence.append(real_val)
            
            if not valid_seq: continue
            if root_val not in sequence: continue # Root bu dizide yoksa geç (1/14 karmaşası için)

            # Bu diziyi oluşturmak için gereken taşları bul
            needed_seq = list(sequence)
            needed_seq.remove(root_val) # Root zaten elimizde
            
            temp_remaining = list(remaining)
            jokers_needed = 0
            for needed_num in needed_seq:
                found = False
                for idx, t in enumerate(temp_remaining):
                    if t['renk'] == root['renk'] and t['sayi'] == needed_num:
                        temp_remaining.pop(idx); found = True; break
                if not found: jokers_needed += 1
            
            if jokers_needed <= jokers:
                valid, rest_score = _solve_partition(temp_remaining, jokers - jokers_needed)
                if valid:
                    # Seri puanı: Serideki sayıların toplamı (Jokerler yerini aldığı sayının değerini alır)
                    current_score = sum(sequence)
                    return True, current_score + rest_score

    return False, 0

def validate_pairs(taslar, okey_tas):
    """Taşların geçerli çiftlerden oluşup oluşmadığını kontrol eder."""
    if len(taslar) % 2 != 0: return False
    
    jokers = 0
    regulars = []
    
    for t in taslar:
        s = int(t['sayi'])
        r = t['renk']
        
        # Okey (Joker) Kontrolü
        if s == okey_tas['sayi'] and r == okey_tas['renk']:
            jokers += 1
        # Sahte Okey (0) -> Okey'in değeri
        elif s == 0:
            regulars.append({'renk': okey_tas['renk'], 'sayi': okey_tas['sayi']})
        else:
            regulars.append({'renk': r, 'sayi': s})
            
    # Gruplama
    counts = {}
    for t in regulars:
        key = (t['renk'], t['sayi'])
        counts[key] = counts.get(key, 0) + 1
        
    needed_jokers = 0
    for key, count in counts.items():
        if count == 1:
            needed_jokers += 1
        elif count > 2:
            return False # Bir taştan 2'den fazla olamaz
            
    return jokers >= needed_jokers

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('join')
def handle_join(data):
    global TUR_SAYISI
    sid = request.sid
    raw_isim = data.get('isim', 'Misafir').strip()
    
    # --- YENİDEN BAĞLANMA (RECONNECT) MANTIĞI ---
    # Eğer bu isimde bir oyuncu zaten varsa, oturumu yeni SID'ye taşı
    existing_sid = None
    for p_sid, p_data in oyun_merkezi['oyuncular'].items():
        if p_data['isim'] == raw_isim:
            existing_sid = p_sid
            break
            
    if existing_sid:
        # Eski oturum verilerini al ve yeni SID'ye aktar
        player_data = oyun_merkezi['oyuncular'].pop(existing_sid)
        oyun_merkezi['oyuncular'][sid] = player_data
        
        # Koltuk bilgisini güncelle
        if player_data['koltuk'] != -1:
            oyun_merkezi['koltuklar'][player_data['koltuk']] = sid
            
        # Masa serilerindeki sahipliği güncelle (Eski SID -> Yeni SID)
        for seri in oyun_merkezi['masa_serileri']:
            if seri['sahip'] == existing_sid:
                seri['sahip'] = sid
                
        join_room("masa1")
        
        # Oyuncuya güncel durumu gönder
        emit('admin_status', {'is_admin': player_data['is_admin']})
        emit('oyuncu_bilgi', {'isim': player_data['isim']})
        emit('taslari_al', {'taslar': player_data['el']})
        if oyun_merkezi['gosterge']: emit('gosterge_belirle', oyun_merkezi['gosterge'])
        emit('atilan_taslari_al', oyun_merkezi['atilan_taslar'])
        emit('masa_guncelle', oyun_merkezi['masa_serileri'])
        
        broadcast_oyuncular()
        aktif_sid = oyun_merkezi['koltuklar'][oyun_merkezi['sira']]
        emit('sira_bilgisi', {'sira': oyun_merkezi['sira'], 'baslayan': oyun_merkezi['baslayan'], 'sure': 60, 'aktif_sid': aktif_sid})
        return # Yeni oyuncu oluşturmadan çık
    # -------------------------------------------
    
    # Benzersiz isim ve Admin kontrolü
    isim = get_unique_name(raw_isim)
    is_admin = (isim.lower() == 'ege')
    
    join_room("masa1")
    
    # OYUN KURULUMU: Sadece ilk oyuncu girdiğinde oyunu sıfırla/kur
    if not oyun_merkezi['oyuncular']:
        TUR_SAYISI += 1
        oyun_merkezi['deste'] = deste_olustur()
        oyun_merkezi['atilan_taslar'] = []
        oyun_merkezi['masa_serileri'] = []
        oyun_merkezi['tur_id'] = 0
        oyun_merkezi['koltuklar'] = [None] * 4
        
        # Başlayan oyuncuyu belirle (Her tur değişir)
        oyun_merkezi['baslayan'] = TUR_SAYISI % 4
        oyun_merkezi['sira'] = 0 # İlk giren (listede 0. index) başlar

        # Göstergeyi (0) olmayan bir taş seçerek belirle
        while True:
            temp = oyun_merkezi['deste'].pop()
            if temp['sayi'] != 0:
                oyun_merkezi['gosterge'] = temp
                oyun_merkezi['okey'] = okey_hesapla(temp)
                break
            else:
                oyun_merkezi['deste'].insert(0, temp)

    # Oyuncuya gösterge ve okey bilgisini gönder
    emit('gosterge_belirle', oyun_merkezi['gosterge'], room=sid)
    
    # Yeni oyuncu katılımı
    if sid not in oyun_merkezi['oyuncular']:
        if len(oyun_merkezi['deste']) < 22: # Deste azaldıysa yenile
            oyun_merkezi['deste'].extend(deste_olustur())
        
        # Boş koltuk bul
        koltuk_no = -1
        for i in range(4):
            if oyun_merkezi['koltuklar'][i] is None:
                koltuk_no = i
                oyun_merkezi['koltuklar'][i] = sid
                break
        
        if koltuk_no != -1:
            # OYUNCU (Koltuk buldu)
            # Başlayan kişiye 22, diğerlerine 21 taş
            tas_sayisi = 22 if koltuk_no == oyun_merkezi['baslayan'] else 21
            el = [oyun_merkezi['deste'].pop() for _ in range(tas_sayisi)]
            takim = 'A' if koltuk_no % 2 == 0 else 'B'
            is_spectator = False
        else:
            # İZLEYİCİ (Koltuk yok)
            tas_sayisi = 0
            el = []
            takim = 'İzleyici'
            is_spectator = True

        oyun_merkezi['oyuncular'][sid] = {
            'isim': isim,
            'el': el,
            'puan': 0,
            'el_acti': False,
            'is_admin': is_admin,
            'is_bot': False,
            'koltuk': koltuk_no,
            'takim': takim,
            'is_spectator': is_spectator
        }
    
    # Admin durumunu bildir
    emit('admin_status', {'is_admin': is_admin})
    
    # Oyuncuya ismini ve puanını bildiren özel mesaj
    emit('oyuncu_bilgi', {'isim': oyun_merkezi['oyuncular'][sid]['isim']})
    
    # Oyuncuya kendi taşlarını gönder
    emit('taslari_al', {'taslar': oyun_merkezi['oyuncular'][sid]['el']})
    
    # Masaya atılan tüm taş geçmişini gönder
    emit('atilan_taslari_al', oyun_merkezi['atilan_taslar'])
    
    broadcast_oyuncular()
    emit('masa_guncelle', oyun_merkezi['masa_serileri'])
    
    # Sıra bilgisini gönder
    # Zamanlayıcıyı başlat
    oyun_merkezi['tur_id'] += 1
    threading.Thread(target=zamanlayici_baslat, args=(oyun_merkezi['tur_id'],)).start()
    
    aktif_sid = oyun_merkezi['koltuklar'][oyun_merkezi['sira']]
    emit('sira_bilgisi', {'sira': oyun_merkezi['sira'], 'baslayan': oyun_merkezi['baslayan'], 'sure': 60, 'aktif_sid': aktif_sid})
    
    # Bot kontrolü
    check_bot_turn()

@socketio.on('tas_cek')
def handle_tas_cek():
    sid = request.sid
    
    # SIRA KONTROLÜ (Koltuk bazlı)
    siradaki_sid = oyun_merkezi['koltuklar'][oyun_merkezi['sira']]
    if sid != siradaki_sid:
        return emit('uyari', {'msg': 'Sıra sizde değil! Sıranızı bekleyin.'})
    
    if oyun_merkezi['oyuncular'][sid].get('is_spectator'):
        return emit('uyari', {'msg': 'İzleyiciler oyuna müdahale edemez!'})
    
    if sid in oyun_merkezi['oyuncular']:
        if len(oyun_merkezi['oyuncular'][sid]['el']) >= 22:
            return emit('uyari', {'msg': 'Zaten taş çektiniz! Elinizdeki fazlalığı atmalısınız.'})

    if oyun_merkezi['deste']:
        yeni_tas = oyun_merkezi['deste'].pop()
        if sid in oyun_merkezi['oyuncular']:
            oyun_merkezi['oyuncular'][sid]['el'].append(yeni_tas)
        
        # Sadece çeken kişiye taşı gönder
        emit('yeni_tas_geldi', yeni_tas, room=sid)
        broadcast_oyuncular()
    else:
        # Deste boşaldıysa masadaki taşları karıştırıp yeni deste yap (Opsiyonel)
        oyun_merkezi['deste'] = deste_olustur()
        handle_tas_cek()

@socketio.on('yandan_tas_al')
def handle_yandan_al():
    sid = request.sid
    
    if sid not in oyun_merkezi['oyuncular']: return
    
    if oyun_merkezi['oyuncular'][sid].get('is_spectator'):
        return emit('uyari', {'msg': 'İzleyiciler oyuna müdahale edemez!'})

    # SIRA KONTROLÜ (Koltuk bazlı)
    siradaki_sid = oyun_merkezi['koltuklar'][oyun_merkezi['sira']]
    if sid != siradaki_sid:
        return emit('uyari', {'msg': 'Sıra sizde değil! Sıranızı bekleyin.'})

    el = oyun_merkezi['oyuncular'][sid]['el']
    if len(el) >= 22:
        return emit('uyari', {'msg': 'Zaten taş çektiniz! Elinizdeki fazlalığı atmalısınız.'})

    if not oyun_merkezi['atilan_taslar']:
        return emit('uyari', {'msg': 'Yerde alınacak taş yok!'})

    # Son atılan taşı al
    discard_info = oyun_merkezi['atilan_taslar'].pop()
    alinan_tas = discard_info['tas']
    el.append(alinan_tas)
    
    # Yandan açma cezası için bilgiyi geçici olarak sakla
    oyun_merkezi['oyuncular'][sid]['yandan_aldi'] = {'tas': alinan_tas, 'atan_sid': discard_info['atan_sid']}
    
    emit('taslari_al', {'taslar': el}) # Sadece oyuncuya
    emit('atilan_taslari_al', oyun_merkezi['atilan_taslar']) # Herkese (yerden eksildi)
    broadcast_oyuncular()

@socketio.on('tas_at')
def handle_tas_at(data):
    sid = request.sid
    
    if sid in oyun_merkezi['oyuncular'] and oyun_merkezi['oyuncular'][sid].get('is_spectator'):
        return emit('uyari', {'msg': 'İzleyiciler oyuna müdahale edemez!'})

    # SIRA KONTROLÜ (Koltuk bazlı)
    siradaki_sid = oyun_merkezi['koltuklar'][oyun_merkezi['sira']]
    if sid != siradaki_sid:
        if sid in oyun_merkezi['oyuncular']:
            emit('taslari_al', {'taslar': oyun_merkezi['oyuncular'][sid]['el']})
        return emit('uyari', {'msg': 'Sıra sizde değil! Sıranızı bekleyin.'})

    if sid in oyun_merkezi['oyuncular'] and len(oyun_merkezi['oyuncular'][sid]['el']) < 22:
        emit('taslari_al', {'taslar': oyun_merkezi['oyuncular'][sid]['el']})
        return emit('uyari', {'msg': 'Önce taş çekmeli veya yandan almalısınız!'})

    # Atılan taşı masaya ekle
    discard_info = {'tas': data, 'atan_sid': sid}
    oyun_merkezi['atilan_taslar'].append(discard_info)
    
    # Oyuncunun elinden bu taşı sil (Senkronizasyon)
    if sid in oyun_merkezi['oyuncular']:
        el = oyun_merkezi['oyuncular'][sid]['el']
        # HTML'den gelen sayıyı (J -> 0) olarak normalize et
        gelen_sayi = 0 if str(data['sayi']) == 'J' else int(data['sayi'])
        for i, tas in enumerate(el):
            if tas['sayi'] == gelen_sayi and tas['renk'] == data['renk']:
                del el[i]
                break
        
        # KAZANMA KONTROLÜ (El bitti mi?)
        if len(el) == 0:
            emit('oyun_bitti', {'kazanan': oyun_merkezi['oyuncular'][sid]['isim']}, room='masa1')
            return # Oyunu bitir, sıra değiştirme veya zamanlayıcı başlatma
    
    # Sırayı bir sonrakine geçir
    oyun_merkezi['sira'] = (oyun_merkezi['sira'] + 1) % 4
    
    # Yeni tur için zamanlayıcıyı başlat
    oyun_merkezi['tur_id'] += 1
    threading.Thread(target=zamanlayici_baslat, args=(oyun_merkezi['tur_id'],)).start()

    # Tüm odaya taşın atıldığını bildir
    aktif_sid = oyun_merkezi['koltuklar'][oyun_merkezi['sira']]
    emit('sira_bilgisi', {'sira': oyun_merkezi['sira'], 'baslayan': oyun_merkezi['baslayan'], 'sure': 60, 'aktif_sid': aktif_sid}, room='masa1')
    emit('yeni_tas_atildi', discard_info, room="masa1")
    broadcast_oyuncular()
    
    # Bot kontrolü
    check_bot_turn()

@socketio.on('el_ac')
def handle_el_ac(data):
    """
    Oyuncu yere seri veya çift açtığında çalışır.
    data: { 'taslar': [{'sayi': 5, 'renk': 'red'}, ...], 'tip': 'seri' }
    """
    sid = request.sid
    player = oyun_merkezi['oyuncular'][sid]
    if player.get('is_spectator'):
        return emit('uyari', {'msg': 'İzleyiciler el açamaz!'})

    taslar = data['taslar']
    tip = data['tip']
    
    # Yandan alınan taşla açma kontrolü
    if player.get('yandan_aldi'):
        yandan_alinan = player['yandan_aldi']
        is_using_discard = any(
            t['sayi'] == yandan_alinan['tas']['sayi'] and t['renk'] == yandan_alinan['tas']['renk'] 
            for t in taslar
        )
        if is_using_discard:
            discarder_sid = yandan_alinan['atan_sid']
            discarder = oyun_merkezi['oyuncular'].get(discarder_sid)
            if discarder and player['takim'] != discarder['takim']:
                penalty_tile = yandan_alinan['tas']
                sayi = 0 if str(penalty_tile['sayi']) == 'J' else int(penalty_tile['sayi'])
                penalty_points = sayi * 10
                discarder_team = discarder['takim']
                for p_data in oyun_merkezi['oyuncular'].values():
                    if p_data['takim'] == discarder_team:
                        p_data['puan'] += penalty_points
                emit('uyari', {'msg': f"{discarder['isim']}'in takımı, atılan taşı açtığınız için {penalty_points} ceza puanı aldı!"})

    # 101 PUAN KONTROLÜ
    if tip == 'seri':
        # 1. PER GEÇERLİLİK KONTROLÜ (1-2-3 veya 7-7-7 kuralı)
        is_valid, hand_score = validate_hand_structure(taslar, oyun_merkezi['okey'])
        
        if not is_valid:
            # CEZA PUANI EKLE (Yapısal Hata)
            if sid in oyun_merkezi['oyuncular']:
                oyun_merkezi['oyuncular'][sid]['puan'] += 101
            emit('uyari', {'msg': 'Hatalı Per! Kurallara uymayan seri. 101 Ceza Puanı Aldınız!'})
            broadcast_oyuncular()
            return

        # 2. PUAN KONTROLÜ
        toplam_puan = hand_score
            
        if toplam_puan < 101:
            # CEZA PUANI EKLE
            if sid in oyun_merkezi['oyuncular']:
                oyun_merkezi['oyuncular'][sid]['puan'] += 101
            
            emit('uyari', {'msg': f'Yetersiz Puan! Toplam: {toplam_puan} (Min 101). 101 Ceza Puanı Aldınız!'})
            broadcast_oyuncular()
            return
    elif tip == 'cift':
        if len(taslar) < 10: # 5 çift = 10 taş
            # CEZA PUANI EKLE (Yetersiz Sayı)
            if sid in oyun_merkezi['oyuncular']:
                oyun_merkezi['oyuncular'][sid]['puan'] += 101
            emit('uyari', {'msg': 'Yetersiz Çift! En az 5 çift gerekli. 101 Ceza Puanı Aldınız!'})
            broadcast_oyuncular()
            return
        
        # ÇİFT GEÇERLİLİK KONTROLÜ (Puan kontrolü yapılmaz, sadece çift mi diye bakılır)
        if not validate_pairs(taslar, oyun_merkezi['okey']):
            # CEZA PUANI EKLE (Geçersiz Çift)
            if sid in oyun_merkezi['oyuncular']:
                oyun_merkezi['oyuncular'][sid]['puan'] += 101
            emit('uyari', {'msg': 'Hatalı Çift! Geçersiz çiftler. 101 Ceza Puanı Aldınız!'})
            broadcast_oyuncular()
            return

    # Masadaki genel listeye ekle
    oyun_merkezi['masa_serileri'].append({
        'sahip': sid,
        'taslar': data['taslar'],
        'tip': data['tip']
    })
    
    # Oyuncunun elinden bu taşları çıkar
    if sid in oyun_merkezi['oyuncular']:
        # Başarılı açılıştan sonra 'yandan_aldi' bayrağını temizle
        if 'yandan_aldi' in oyun_merkezi['oyuncular'][sid]:
            del oyun_merkezi['oyuncular'][sid]['yandan_aldi']
            
        el = oyun_merkezi['oyuncular'][sid]['el']
        # Oyuncuyu el açmış olarak işaretle
        oyun_merkezi['oyuncular'][sid]['el_acti'] = True
        
        for acilan in data['taslar']:
            a_sayi = 0 if str(acilan['sayi']) == 'J' else int(acilan['sayi'])
            for i, tas in enumerate(el):
                if tas['sayi'] == a_sayi and tas['renk'] == acilan['renk']:
                    del el[i]
                    break
        
        # Başarılı işlem sonrası eli senkronize et (Garantilemek için)
        emit('taslari_al', {'taslar': el})
    
    # Herkesin ekranındaki yan paneli güncelle
    broadcast_oyuncular()
    emit('masa_guncelle', oyun_merkezi['masa_serileri'], room="masa1")

@socketio.on('islek_yap')
def handle_islek_yap(data):
    sid = request.sid
    if sid not in oyun_merkezi['oyuncular']: return
    
    player = oyun_merkezi['oyuncular'][sid]
    if player.get('is_spectator'):
        return emit('uyari', {'msg': 'İzleyiciler işlek yapamaz!'})

    if not player['el_acti']:
        emit('uyari', {'msg': 'İşlek yapmak için önce elinizi açmalısınız!'})
        return

    set_index = data.get('set_index')
    tas_data = data.get('tas')
    
    if set_index is None or not tas_data: return
    if set_index < 0 or set_index >= len(oyun_merkezi['masa_serileri']): return
    
    target_set = oyun_merkezi['masa_serileri'][set_index]
    
    # 1. Taşın oyuncunun elinde olup olmadığını kontrol et
    el = player['el']
    found_index = -1
    s_sayi = 0 if str(tas_data['sayi']) == 'J' else int(tas_data['sayi'])
    
    for i, t in enumerate(el):
        if t['renk'] == tas_data['renk'] and t['sayi'] == s_sayi:
            found_index = i
            break
            
    if found_index == -1:
        emit('uyari', {'msg': 'Bu taş elinizde yok!'})
        return
        
    real_tile = el[found_index]
    
    # 2. Taşı seriye ekleyip geçerli olup olmadığını kontrol et
    # Mevcut seri + yeni taş
    yeni_seri_taslari = target_set['taslar'] + [real_tile]
    
    # Doğrulama fonksiyonunu kullan
    is_valid, _ = validate_hand_structure(yeni_seri_taslari, oyun_merkezi['okey'])
    
    if is_valid:
        # Geçerliyse ekle ve sırala
        target_set['taslar'] = yeni_seri_taslari
        
        # Görsel düzgünlük için sıralama (Basitçe sayıya göre)
        # Not: Okey taşları (Jokerler) sıralamayı bozabilir ama validate yapısı korur.
        # Gruplar (7-7-7) için renk sırası, Seriler (1-2-3) için sayı sırası.
        r_oncelik = {'red': 1, 'black': 2, 'blue': 3, 'orange': 4}
        target_set['taslar'].sort(key=lambda x: (x['sayi'], r_oncelik.get(x['renk'], 9)))
        
        # Oyuncunun elinden sil
        del el[found_index]
        emit('taslari_al', {'taslar': el})
        broadcast_oyuncular()
        emit('masa_guncelle', oyun_merkezi['masa_serileri'], room="masa1")
    else:
        emit('uyari', {'msg': 'Bu taş bu seriye işlenemez!'})

@socketio.on('take_okey')
def handle_take_okey(data):
    sid = request.sid
    if sid not in oyun_merkezi['oyuncular']: return
    
    player = oyun_merkezi['oyuncular'][sid]
    if player.get('is_spectator'):
        return emit('uyari', {'msg': 'İzleyiciler okey alamaz!'})

    set_index = data.get('set_index')
    replacing_tile_data = data.get('tas')
    
    if set_index is None or not replacing_tile_data: return
    if set_index < 0 or set_index >= len(oyun_merkezi['masa_serileri']): return
    
    target_set = oyun_merkezi['masa_serileri'][set_index]
    
    # Kural: Takım arkadaşının okeyi alınmaz
    owner_sid = target_set['sahip']
    owner = oyun_merkezi['oyuncular'].get(owner_sid)
    if not owner or owner['takim'] == player['takim']:
        return emit('uyari', {'msg': 'Kendi takım arkadaşınızın okeyini alamazsınız!'})
        
    # Taşı oyuncunun elinde bul
    el = player['el']
    found_index = -1
    s_sayi = 0 if str(replacing_tile_data['sayi']) == 'J' else int(replacing_tile_data['sayi'])
    for i, t in enumerate(el):
        if t['renk'] == replacing_tile_data['renk'] and t['sayi'] == s_sayi:
            found_index = i
            break
    if found_index == -1: return emit('uyari', {'msg': 'Bu taş elinizde yok!'})
    
    replacing_tile = el[found_index]
    
    # Hedef setteki okeyi bul
    okey_tas = oyun_merkezi['okey']
    set_tiles_without_okey = [t for t in target_set['taslar'] if not (t['renk'] == okey_tas['renk'] and t['sayi'] == okey_tas['sayi'])]
    
    if len(target_set['taslar']) == len(set_tiles_without_okey):
        return emit('uyari', {'msg': 'Bu perde alınacak okey yok!'})
        
    # Yeni taşı ekleyip geçerli bir per oluşturuyor mu diye kontrol et
    temp_set_tiles = set_tiles_without_okey + [replacing_tile]
    is_valid_new_set, _ = validate_hand_structure(temp_set_tiles, okey_tas)
    
    if is_valid_new_set:
        del el[found_index]
        el.append(okey_tas)
        target_set['taslar'] = temp_set_tiles
        r_oncelik = {'red': 1, 'black': 2, 'blue': 3, 'orange': 4}
        target_set['taslar'].sort(key=lambda x: (x['sayi'], r_oncelik.get(x['renk'], 9)))
        for p_data in oyun_merkezi['oyuncular'].values():
            if p_data['takim'] == owner['takim']: p_data['puan'] += 101
        emit('uyari', {'msg': f"Okeyi aldınız! {owner['isim']}'in takımı 101 ceza puanı aldı!"})
        emit('taslari_al', {'taslar': el})
        emit('masa_guncelle', oyun_merkezi['masa_serileri'], room="masa1")
        broadcast_oyuncular()
    else:
        emit('uyari', {'msg': 'Bu taş okeyin yerine geçemez!'})

@socketio.on('sirala')
def handle_sirala(data):
    # Sunucu tarafında el sıralamasını güncelle (İsteğe bağlı)
    sid = request.sid
    tip = data.get('tip')
    if sid in oyun_merkezi['oyuncular']:
        el = oyun_merkezi['oyuncular'][sid]['el']
        r_oncelik = {'red': 1, 'black': 2, 'blue': 3, 'orange': 4}
        if tip == 'renk':
            el.sort(key=lambda x: (r_oncelik.get(x['renk'], 9), x['sayi']))
        else:
            el.sort(key=lambda x: (x['sayi'], r_oncelik.get(x['renk'], 9)))

@socketio.on('yeni_oyun')
def handle_yeni_oyun():
    """Oyunu sıfırlar ve mevcut oyuncularla yeniden başlatır."""
    sender_sid = request.sid
    # Sadece admin (Ege) oyunu sıfırlayabilir
    if sender_sid not in oyun_merkezi['oyuncular'] or not oyun_merkezi['oyuncular'][sender_sid].get('is_admin'):
        return

    global TUR_SAYISI
    TUR_SAYISI += 1
    oyun_merkezi['deste'] = deste_olustur()
    oyun_merkezi['atilan_taslar'] = []
    oyun_merkezi['masa_serileri'] = []
    oyun_merkezi['tur_id'] += 1 # Eski zamanlayıcıları iptal eder
    
    # Başlayan oyuncuyu belirle
    oyun_merkezi['baslayan'] = TUR_SAYISI % 4
    oyun_merkezi['sira'] = oyun_merkezi['baslayan']

    # Yeni Gösterge
    while True:
        temp = oyun_merkezi['deste'].pop()
        if temp['sayi'] != 0:
            oyun_merkezi['gosterge'] = temp
            oyun_merkezi['okey'] = okey_hesapla(temp)
            break
        else:
            oyun_merkezi['deste'].insert(0, temp)
            
    emit('gosterge_belirle', oyun_merkezi['gosterge'], room='masa1')

    # Mevcut oyunculara yeniden taş dağıt
    # Koltuk sırasına göre dağıt
    for i in range(4):
        sid = oyun_merkezi['koltuklar'][i]
        if not sid: continue
        
        # Başlayan kişiye 22, diğerlerine 21 taş
        # Baslayan indexi koltuk indexidir
        count = 22 if i == oyun_merkezi['baslayan'] else 21
        
        # Deste yetmezse ekle (Teorik koruma)
        if len(oyun_merkezi['deste']) < count: oyun_merkezi['deste'].extend(deste_olustur())
        
        oyun_merkezi['oyuncular'][sid]['el'] = [oyun_merkezi['deste'].pop() for _ in range(count)]
        oyun_merkezi['oyuncular'][sid]['puan'] = 0 # Puanları sıfırla
        
        emit('taslari_al', {'taslar': oyun_merkezi['oyuncular'][sid]['el']}, room=sid)

    emit('atilan_taslari_al', [], room='masa1')
    emit('masa_guncelle', [], room='masa1')
    aktif_sid = oyun_merkezi['koltuklar'][oyun_merkezi['sira']]
    emit('sira_bilgisi', {'sira': oyun_merkezi['sira'], 'baslayan': oyun_merkezi['baslayan'], 'sure': 60, 'aktif_sid': aktif_sid}, room='masa1')
    emit('oyun_sifirlandi', {}, room='masa1') # Ekranı kapat
    broadcast_oyuncular()
    threading.Thread(target=zamanlayici_baslat, args=(oyun_merkezi['tur_id'],)).start()
    check_bot_turn()

@socketio.on('admin_add_bot')
def handle_admin_add_bot(data):
    sender_sid = request.sid
    # Sadece admin ekleyebilir
    if sender_sid not in oyun_merkezi['oyuncular'] or not oyun_merkezi['oyuncular'][sender_sid].get('is_admin'):
        return
    
    difficulty = data.get('difficulty', 'kolay')
    bot_sid = f"bot_{uuid.uuid4().hex[:8]}"
    bot_name = get_unique_name(f"Bot ({difficulty.capitalize()})")
    
    # Botu oyuna dahil et (handle_join mantığına benzer)
    tas_sayisi = 22 if len(oyun_merkezi['oyuncular']) == 0 else 21
    
    # Deste kontrolü
    if len(oyun_merkezi['deste']) < tas_sayisi:
        oyun_merkezi['deste'].extend(deste_olustur())
        
    # Boş koltuk bul
    koltuk_no = -1
    for i in range(4):
        if oyun_merkezi['koltuklar'][i] is None:
            koltuk_no = i
            oyun_merkezi['koltuklar'][i] = bot_sid
            break
            
    oyun_merkezi['oyuncular'][bot_sid] = {
        'isim': bot_name,
        'el': [oyun_merkezi['deste'].pop() for _ in range(tas_sayisi)],
        'puan': 0,
        'el_acti': False,
        'is_admin': False,
        'is_bot': True,
        'bot_difficulty': difficulty,
        'koltuk': koltuk_no,
        'takim': 'A' if koltuk_no % 2 == 0 else 'B'
    }
    
    broadcast_oyuncular()
    # Eğer sıra botta ise (oyun yeni başladıysa vs) tetikle
    check_bot_turn()

@socketio.on('admin_rename_player')
def handle_admin_rename(data):
    sender_sid = request.sid
    # Sadece admin düzenleyebilir
    if sender_sid not in oyun_merkezi['oyuncular'] or not oyun_merkezi['oyuncular'][sender_sid].get('is_admin'):
        return
        
    target_sid = data.get('target_sid')
    new_name = data.get('new_name')
    
    if target_sid in oyun_merkezi['oyuncular']:
        final_name = get_unique_name(new_name)
        oyun_merkezi['oyuncular'][target_sid]['isim'] = final_name
        broadcast_oyuncular()

@socketio.on('voice_signal')
def handle_voice_signal(data):
    """WebRTC sesli sohbet sinyallerini yönlendirir."""
    target_sid = data.get('target')
    signal = data.get('signal')
    sender_sid = request.sid
    
    if target_sid:
        emit('voice_signal', {'sender': sender_sid, 'signal': signal}, room=target_sid)

if __name__ == '__main__':
    print("----------------------------------------------------------------")
    print("Oyun Sunucusu Başlatıldı! http://localhost:5001 adresinden girebilirsiniz.")
    print("Eğer arkadaşlarınızla oynayacaksanız, bu pencereyi KAPATMAYIN.")
    print("----------------------------------------------------------------")
    # Oyun 5001 portunda başlıyor
    # Tünel bağlantılarında (ssh/ngrok) debug modu sorun çıkarabilir, False yapıyoruz.
    socketio.run(app, host='0.0.0.0', port=5001, debug=False)
    # Bulut sunucu için PORT ortam değişkenini kullan
    port = int(os.environ.get("PORT", 5001))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)