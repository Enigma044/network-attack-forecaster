# Deploying the Network Attack Forecaster

The app is a single container: a FastAPI server (`netforecast/api.py`) that also serves the built
React dashboard. The image holds both trained models, the synthetic practice data and one real,
held-out CIC-IDS-2018 day (Thursday 01-03-2018, 103 MB). It does not include the full 2.8 GB dataset.

## What the container does differently from local runs

| Setting | Container default | Why |
|---|---|---|
| `NETFORECAST_PUBLIC=1` | on | turns off “Build the practice model” (`POST /api/demo/build` returns 403), so visitors can't make the server retrain |
| `NETFORECAST_MAX_UPLOAD_MB=1024` | 1 GB | refuses bigger uploads with HTTP 413. Uploads are streamed to a temporary file on disk (deleted afterwards), not held in memory |
| `PORT=7860` | 7860 | the port Hugging Face Spaces expects |
| user | uid 1000, non-root | required by Hugging Face; safer anywhere |
| `GET /api/health` | health check | used by the image's `HEALTHCHECK` |

Library versions are pinned in `requirements-deploy.txt` (and torch 2.14.0 CPU in the `Dockerfile`), so the
saved scikit-learn and PyTorch model files load exactly as trained.

## 1. Run the image on any machine (fully offline once built)

```bash
# build (Podman shown; with Docker use `docker build -t netforecast .`)
podman build --format docker -t netforecast .

# run, then open http://localhost:8000
podman run --rm -p 8000:7860 netforecast
```

The first build downloads base images and CPU PyTorch (≈ 6 min); rebuilds after code changes take seconds.
The image is about 1.5 GB. The server uses about 0.7 GB of RAM after analysing a full real day, which takes about 8 s.

To hand the image to someone without a registry:

```bash
podman save -o netforecast.tar netforecast        # on your machine
podman load -i netforecast.tar                    # on theirs, then `podman run` as above
```

## 2. Public link on Hugging Face Spaces (free CPU: 2 vCPU, 16 GB RAM)

1. Create a Space at <https://huggingface.co/new-space> and choose **SDK: Docker**, hardware **CPU basic**, and the Blank template.
2. Clone it next to this project and copy the app in:
   ```bash
   git clone https://huggingface.co/spaces/<your-user>/<space-name> hf-space
   cd hf-space
   rsync -a --exclude .git --exclude .venv --exclude 'frontend/node_modules' --exclude 'frontend/dist' \
         --exclude 'data/cic2018/*' --exclude tests ../sih-2026-153/ ./
   mkdir -p data/cic2018
   cp ../sih-2026-153/data/cic2018/Thursday-01-03-2018_TrafficForML_CICFlowMeter.csv data/cic2018/
   ```
3. Spaces reads its settings from the front matter of `README.md`. Put this block at the very top of the Space's README (only in the Space repo; GitHub doesn't need it):
   ```yaml
   ---
   title: Network Attack Forecaster
   emoji: 🛡️
   colorFrom: blue
   colorTo: gray
   sdk: docker
   app_port: 7860
   pinned: false
   ---
   ```
4. Files over 10 MB must go through Git LFS, and `data/` is in `.gitignore`, so add it explicitly:
   ```bash
   git lfs install
   git lfs track "*.csv" "*.pt" "*.joblib"
   git add .gitattributes
   git add -f data/cic2018/Thursday-01-03-2018_TrafficForML_CICFlowMeter.csv data/synthetic
   git add .
   git commit -m "Deploy Network Attack Forecaster"
   git push
   ```
5. The Space builds the same `Dockerfile` (≈ 6–8 min the first time) and serves at
   `https://<your-user>-<space-name>.hf.space`.

## 3. Temporary link from your laptop (for a live demo or the demo video)

```bash
.venv/bin/uvicorn netforecast.api:app --port 8000                 # terminal 1 (or the podman run above)
cloudflared tunnel --url http://localhost:8000                     # terminal 2; prints https://….trycloudflare.com
```

The link lives only while both commands run. `ngrok http 8000` works the same way.

## Not suitable

- **Vercel / Netlify**: they host static frontends and short serverless functions, but this needs a long-running Python + PyTorch process.
- **Render / Railway free tiers**: 512 MB RAM is not enough for PyTorch plus a full-day analysis.
