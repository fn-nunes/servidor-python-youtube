# Servidor Python: YouTube e HTTPS

API REST com FastAPI.

## Endpoints

- `GET /` - informações do serviço
- `GET /health` - verificação de saúde
- `GET /youtube/transcript?url=URL_DO_VIDEO` - obtém legendas disponíveis
- `GET /web/fetch?url=https://exemplo.com` - consulta página HTTPS e retorna HTML

Documentação interativa: `/docs`.

## Executar localmente

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

## Observações

A extração do YouTube depende de legendas acessíveis. O endpoint HTTPS aceita apenas HTTPS e bloqueia destinos IP não públicos, mas, antes de expor a API amplamente, recomenda-se adicionar autenticação, limites de requisições e proteção adicional contra abuso.
