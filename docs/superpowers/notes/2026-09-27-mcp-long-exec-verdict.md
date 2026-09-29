# Verdict — a long governed exec never returned (#238 live fix, second defect)

**Esito:** la causa è il **read timeout dello stream SSE del client MCP**, 300 s
di default. Un comando che gira più a lungo non produce eventi nella finestra, lo
stream viene chiuso e il risultato non arriva mai: il pod attende per sempre, il
job resta `in_progress`, la run non chiude.

## Come ci si è arrivati

Il primo difetto (concorrenza non applicata) è stato diagnosticato e corretto
(`docs/superpowers/notes/2026-09-25-live-concurrency-verdict.md`). Il fix ha
smesso di lasciare il traffico non governato, e quindi un comando reale ha
cominciato a durare quanto la policy misurata impone: `ffuf` con 4.750 richieste,
10 rps, `max_concurrency = 1` → ~20 minuti (prima: ~20 secondi, perché non
governato).

Da lì, in due tentativi di `gate-twice`, sempre lo stesso sintomo:

- nessun processo `ffuf` più vivo nel container kali;
- nessun lease attivo nel registry (il lease era stato rilasciato);
- processo MCP **idle**, nessuna richiesta HTTP successiva nei log;
- job `in_progress`, agent in attesa, run che non arriva al terminale;
- il bersaglio non riceve più nulla.

## L'esperimento discriminante (una sola variabile)

Comando identico (`sleep 360; echo PROBE_DONE`), stack identico, unica differenza
il parametro `sse_read_timeout` della config del server MCP:

| Variante | Esito |
|---|---|
| default (300 s) | **mai tornato** entro 780 s (ucciso da `timeout`, nessun output) |
| `sse_read_timeout = 1800` | **`RETURNED after 360.1s`**, `returncode=0`, `PROBE_DONE` |

Log MCP della variante riuscita: `POST /mcp 202` + `GET /mcp` a t+0 e, a t+360 s,
la `POST`/`DELETE` di completamento della sessione — cioè lo stream è rimasto vivo
per tutta la durata del comando.

## Perché è la finestra a essere sbagliata

`langchain-mcp-adapters` 0.3.2 costruisce il client streamable-HTTP così:

```python
DEFAULT_STREAMABLE_HTTP_SSE_READ_TIMEOUT = timedelta(seconds=60 * 5)   # 300 s
client_factory(timeout=httpx.Timeout(timeout_seconds, read=sse_read_timeout_seconds))
```

Il read timeout di httpx è **per evento**, quindi vale esattamente come "nessun
evento per 300 s ⇒ lo stream muore". Con il traffico non governato nessun comando
arrivava a 300 s e il difetto era invisibile; con la policy imposta ci arriva
qualunque job rich-intensive. Non è un difetto del governor: è il canale che porta
i comandi al bersaglio.

## Fix applicati (entrambi necessari)

1. **La finestra dello stream deriva dal bound del comando**
   (`_mcp_sse_read_timeout_s`): mai sotto i 300 s di default, altrimenti
   `timeout_s + 120 s` di margine per la coda (lookup dei ref di cattura,
   rilascio del lease, envelope).
2. **Bound esplicito sul singolo tool call** (`_mcp_call_timeout_s` + `asyncio.wait_for`):
   se il trasporto perde la risposta, l'exec fallisce **rumorosamente**
   (`returncode=124`, `stderr` esplicito) e il pod può ritentare/degradare. Mai
   più un'attesa infinita che lascia la run appesa fino al reaper.

Test: `tests/recon/test_pod_mcp_call_bounds.py` (4 test, RED prima del fix).
Mutazione uccisa: rimuovendo il bound, la chiamata "persa" torna `rc=0` invece di
`rc=124` — il test fallisce.

## Prova end-to-end dopo il fix

Seam di produzione, con lo stack E2E reale:

```
default_exec_fn('sleep 360; echo PROBE_DONE', 'diag-bound-probe', 600)
→ RETURNED after 360.3s rc=0 stdout='PROBE_DONE'
```

Prima del fix, lo stesso comando sullo stesso seam non tornava mai.
