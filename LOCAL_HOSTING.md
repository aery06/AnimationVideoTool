# Local Hosting Notes

Default address: `http://127.0.0.1:7860`

Environment variables:
- `AEV_HOST`: bind address, default `127.0.0.1`
- `AEV_PORT`: port, default `7860`
- `AEV_INBROWSER`: `1` or `0`
- `AEV_TTS_CMD`: optional explicit eSpeak/eSpeak NG executable

For local-only use, keep the bind address as `127.0.0.1`. Docker maps container port 7860 only to the host port specified in `docker-compose.yml`.
