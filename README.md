# FloodAlert — Vercel + Supabase

ระบบเว็บสำหรับติดตามสภาพอากาศและสถานการณ์ที่เกี่ยวข้องกับน้ำท่วม โดยใช้ Flask และ PostgreSQL (Supabase) พร้อม Dashboard แบบ Ocean Monitor

## ฟีเจอร์หลัก

- Dashboard สาธารณะ ดู Forecast ได้โดยไม่ต้อง Login
- เพิ่ม/ลบพื้นที่ได้เฉพาะผู้ที่ Login แล้ว
- เลือกพื้นที่แบบ จังหวัด → อำเภอ/เขต → ตำบล/แขวง
- รองรับ 77 จังหวัด
- TMD NWP Forecast API ผ่าน Personal Access Token
- Forecast 24 ชั่วโมง พร้อมกราฟและ Timeline
- Summary สถานการณ์และระดับเฝ้าระวังจากข้อมูล Forecast ของระบบ
- แผนที่ Leaflet พร้อม Marker และ Legend
- ประกาศเตือนภัย TMD แยกจากระดับที่ระบบคำนวณ
- Responsive Desktop / Tablet / Mobile
- PostgreSQL-ready สำหรับ Supabase
- Vercel Flask entry point (`app.py`)
- Vercel Cron endpoint สำหรับ refresh ข้อมูลตามตารางเวลา

## โครงสร้างสำหรับ Vercel

```text
app.py                         # Vercel/Flask entry point
run.py                         # สร้าง Flask app
vercel.json                    # Vercel configuration + Cron
requirements.txt
floodalert/
├─ auth.py
├─ locations.py
├─ main.py
├─ models.py
├─ provinces.py
├─ risk_service.py
├─ scheduler.py
├─ tmd_api.py
├─ warning_service.py
├─ weather_service.py
├─ static/
└─ templates/
```

## Deploy บน Vercel + Supabase

1. นำไฟล์ทั้งหมดในโฟลเดอร์นี้ขึ้น GitHub โดยให้ `app.py`, `run.py`, `requirements.txt`, `vercel.json` และโฟลเดอร์ `floodalert/` อยู่ที่ root ของ repository
2. Import repository ใน Vercel และใช้ repository root เป็น Root Directory
3. ไม่ต้องใส่ Build Command แบบ custom สำหรับ Flask framework detection
4. ตั้ง Environment Variables:
   - `SECRET_KEY`
   - `DATABASE_URL`
   - `TMD_ACCESS_TOKEN`
   - `TMD_WARNING_URL` (optional)
   - `CRON_SECRET`
5. Deploy Production

Vercel รองรับ Flask โดยตรงด้วย Python runtime และ framework detection ปัจจุบันรองรับ root `app.py`. โปรเจกต์นี้ใช้ `app.py` เป็น entry point และเก็บ package จริงไว้ใน `floodalert/` เพื่อไม่ให้ชื่อชนกับ entry module.

## Environment Variables

ตัวอย่างใน `.env.example` ใช้สำหรับ local development เท่านั้น ห้าม commit `.env` ที่มีค่า secret จริง

`DATABASE_URL` ควรเป็น PostgreSQL connection string จาก Supabase เช่น:

```text
postgresql://postgres.PROJECT-REF:PASSWORD@...pooler.supabase.com:5432/postgres
```

## Vercel Cron

`vercel.json` ตั้ง Cron ไปที่ `/api/cron/refresh` วันละครั้งเพื่อ refresh Forecast ของพื้นที่ที่ติดตามและ Warning data. Endpoint ตรวจ `Authorization: Bearer <CRON_SECRET>` ก่อนทำงาน

Cron บน Hobby มีความถี่ขั้นต่ำวันละครั้ง จึงไม่แทน APScheduler แบบ 10–15 นาทีบน local ได้ทั้งหมด. สำหรับ refresh ที่ถี่กว่านี้ควรใช้ scheduler ภายนอก/ฐานข้อมูลหรือแผนที่รองรับความถี่ที่ต้องการ

## Local development

```powershell
python -m pip install -r requirements.txt
python -m compileall floodalert
python run.py
```

เมื่อไม่ได้ตั้ง `DATABASE_URL` ระบบจะ fallback ไปใช้ SQLite ในเครื่อง

## API สำคัญ

- `/` — หน้าหลัก
- `/dashboard` — Dashboard สาธารณะ / Dashboard พื้นที่ส่วนตัว
- `/api/provinces`
- `/api/locations/districts?province=...`
- `/api/locations/subdistricts?province=...&district=...`
- `/api/forecast?province=...&district=...&subdistrict=...`
- `/api/forecast/all`
- `/api/warnings`
- `/healthz`
- `/api/cron/refresh` — scheduled refresh (protected by `CRON_SECRET` on Vercel)

## ความหมายของระดับสี

ระดับสีบน Dashboard เป็นตัวชี้วัดของแอปพลิเคชันจากข้อมูล Forecast เช่น ฝนและลม ไม่ใช่ประกาศเตือนภัยอย่างเป็นทางการ รายละเอียดการประมวลผลอยู่ใน `floodalert/weather_service.py` และ `floodalert/risk_service.py`

## Performance v2

- Dashboard HTML renders without waiting for TMD warning calls.
- Leaflet and Chart.js load only on the dashboard.
- Forecast and warning requests start in parallel after the dashboard shell is visible.
- Forecast-all API groups a single 24-hour database read instead of N+1 queries.
- Browser session cache shows the last dashboard data immediately for up to 60 seconds, then revalidates in the background.
- The public home prefetches the lightweight dashboard shell.
