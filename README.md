# Cisco Router Monitor

Web-GUI, die sich per SSH mit einem Cisco-Router/CUBE verbindet und periodisch
`show sip-ua register status` abfragt, um SIP-Trunk-Registrierungen zu
überwachen. Enthält außerdem einen Debug-Tab (`debug ccsip messages` /
`undebug all`) und einen `/healthz`-Endpunkt für externes Monitoring
(z. B. Uptime Kuma).

## Lokal mit Docker Compose

```bash
docker compose up -d --build
```

Danach `http://<host>:8000` öffnen und im Einstellungen-Tab verbinden.
Host/Nutzer/Labels landen in einem benannten Volume (`cisco-monitor-data`)
und überleben damit ein Neuerstellen des Containers.

Bei SSH-Key-Login: den privaten Schlüssel read-only in den Container
mounten (Zeile in `docker-compose.yml` einkommentieren und Pfad anpassen)
und im Einstellungen-Tab als Pfad *innerhalb* des Containers eintragen,
z. B. `/keys/id_rsa`.

## Deployment über Gitea + Portainer

1. Repo in Gitea anlegen und dieses Projekt dorthin pushen (siehe unten).
2. In Portainer: **Stacks → Add stack → Repository**.
3. Repository-URL der Gitea-Instanz eintragen (bei privatem Repo:
   Zugangsdaten/Token hinterlegen), Branch `main`, Compose-Pfad
   `docker-compose.yml`.
4. Deploy the stack. Portainer baut das Image anhand des `Dockerfile` und
   startet den Container.

Für Updates: Änderungen nach Gitea pushen, in Portainer den Stack erneut
"Pull and redeploy".

## Sicherheitshinweise

- Kein eigenes Auth/Login in der GUI - nur in einem vertrauenswürdigen
  Netz betreiben oder hinter einem Reverse-Proxy mit Authentifizierung.
- `config.json` (im `/data`-Volume) kann im Klartext ein SSH-Passwort
  bzw. eine Key-Passphrase enthalten, falls du eines davon einträgst -
  Zugriff auf das Volume entsprechend einschränken.
