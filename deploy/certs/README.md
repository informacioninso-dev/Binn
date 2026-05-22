Coloca aqui los certificados si quieres terminar TLS dentro de Nginx usando:

- `fullchain.pem`
- `privkey.pem`

Luego levanta el stack con:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml -f docker-compose.prod.tls.yml up -d
```
