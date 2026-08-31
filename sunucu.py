from flask import Flask, request, jsonify
import os
import csv
import base64
import requests
import time
from datetime import datetime
import threading

# --- GEMINI & BLYNK AYARLARI ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AQ.Ab8RN6JAPddJXYE0HCQTQhAdNuN1PeyxPLru7Jt3eN5sXf-tvA")
BLYNK_AUTH_TOKEN = "Ir_GGYSTnoWsfC43dv7JRW4-tC7ThGTU"

app = Flask(__name__)

UPLOAD_FOLDER = './uploads'
CSV_FILE = 'su_saati_kayitlari.csv'

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Tarih_Saat', 'Okunan_Endeks_m3', 'Dosya_Yolu'])

def send_to_blynk(pin, value):
    """Okunan veriyi Blynk Mobil Uygulamasına Gönderir"""
    try:
        url = f"https://blynk.cloud/external/api/update?token={BLYNK_AUTH_TOKEN}&{pin}={value}"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            print(f"[+] Blynk Güncellendi: {pin} -> {value}")
        else:
            print(f"[-] Blynk Güncelleme Hatası ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"[-] Blynk Bağlantı Hatası: {e}")

@app.route('/')
def home():
    return "ESP32-CAM AI Su Saati Sunucusu Bulutta Çalışıyor!"

def analyze_image_background(image_data, save_path):
    print("[*] Yapay zeka arkaplanda su saatini analiz ediyor...")
    
    base64_image = base64.b64encode(image_data).decode('utf-8')
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [{
            "parts": [
                {
                    "text": (
                        "Bu görsel bir su saatine / su sayacına aittir. "
                        "Sayaç üzerindeki siyah ve kırmızı bölmelerdeki tüm sayısal değeri (m3 cinsinden endeksi) oku. "
                        "Cevap olarak SADECE okuduğun sayıyı ver (örneğin: 00123.456 veya 123.45). "
                        "Açıklama veya ek kelime yazma, sadece rakam dön."
                    )
                },
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": base64_image
                    }
                }
            ]
        }]
    }

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=60)
            
            if response.status_code == 200:
                result = response.json()
                okunan_deger = result['candidates'][0]['content']['parts'][0]['text'].strip()
                tarih_saat = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                print("\n==================================================")
                print(f"🤖 YAPAY ZEKA OKUMA SONUCU: {okunan_deger} m³")
                print(f"📅 TARİH: {tarih_saat}")
                print("==================================================\n")

                # 1. CSV Kaydı
                with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([tarih_saat, okunan_deger, save_path])

                # 2. Blynk Mobil Uygulamasına Gönder (V0 Pinine)
                send_to_blynk("v0", okunan_deger)
                break
            else:
                print(f"[!] Gemini API Yanıt Hatası ({response.status_code}): {response.text}")
                time.sleep(2)

        except requests.exceptions.Timeout:
            print(f"[!] Deneme {attempt}/{max_retries}: Gemini API zaman aşımına uğradı (60sn), tekrar deneniyor...")
            time.sleep(2)
        except Exception as e:
            print(f"[-] Arkaplan Analiz Hatası: {e}")
            break

@app.route('/upload-meter', methods=['POST'])
def upload_meter():
    image_data = request.data
    
    if not image_data:
        print("[-] Hata: Boş veri geldi.")
        return jsonify({"status": "error", "message": "Görsel verisi boş"}), 400

    save_path = os.path.join(UPLOAD_FOLDER, 'meter.jpg')
    with open(save_path, 'wb') as f:
        f.write(image_data)

    print(f"[+] Fotoğraf kaydedildi -> {save_path}")

    threading.Thread(target=analyze_image_background, args=(image_data, save_path)).start()

    return jsonify({
        "status": "success", 
        "message": "Fotoğraf alındı, analiz arkaplanda başlatıldı"
    }), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
