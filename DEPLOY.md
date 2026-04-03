# Deploy Gravity Well to Render

## Quick Deploy (Blueprint)

1. **Push to GitHub:**
```bash
git init && git add . && git commit -m "Gravity Well v0.3"
# Create repo on GitHub, then:
git remote add origin https://github.com/YOUR_USERNAME/gravitywell.git
git branch -M main && git push -u origin main
```

2. **Deploy via Render Blueprint:**
   - Go to https://dashboard.render.com/blueprints
   - Click "New Blueprint Instance"
   - Connect your GitHub repo
   - Render auto-creates database + web service from `render.yaml`

3. **Set environment variables** (Render dashboard → your service → Environment):
   - `ZENODO_TOKEN`: Your Zenodo API token
   - `ADMIN_TOKEN`: A strong random string for admin operations

4. **Test:**
```bash
curl https://gravitywell.onrender.com/v1/health
```

## Manual Deploy (if Blueprint doesn't work)

### 1. Create PostgreSQL
- Render → New+ → PostgreSQL → Free plan → Create
- Copy the "Internal Database URL"

### 2. Create Web Service
- Render → New+ → Web Service → Connect repo
- **Build:** `pip install -r requirements.txt`
- **Start:** `uvicorn main:app --host 0.0.0.0 --port 10000`
- **Environment:**
  - `DATABASE_URL`: (from step 1)
  - `ZENODO_TOKEN`: your token
  - `ADMIN_TOKEN`: your admin secret
  - `API_BASE_URL`: `https://gravitywell.onrender.com`

### 3. Create Your First API Key
```bash
curl -X POST https://gravitywell.onrender.com/v1/admin/keys/create?label=primary \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN"
```

## Free Tier Notes

- Web service spins down after 15 min idle (~30s cold start)
- PostgreSQL: 1GB, expires after 90 days (can recreate — Zenodo is the real archive)
- Upgrade to always-on: $7/month

## After Deploy

Run `test.sh` to verify the full flow:
```bash
API_URL=https://gravitywell.onrender.com ADMIN_TOKEN=your_token ./test.sh
```
