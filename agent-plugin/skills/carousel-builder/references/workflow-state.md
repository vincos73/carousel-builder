# Stato, ricevute ed evidenze del workflow locale

Usare questa procedura soltanto con un nuovo manifest schema `1.4` nel percorso `local-editor`, cioè con `production.mode: renderer` e `production.producer: approved-preview-dom-v2`. I manifest 1.3 e precedenti restano leggibili come legacy ma non sono avanzabili da questa CLI senza una migrazione esplicita e nuove approvazioni. Un adapter esterno o il fallback `layout` deve applicare i propri gate verificabili: non eseguire questa CLI, non copiare le sue ricevute e non presentare i suoi controlli come superati.

Il percorso canonico è:

```text
bozza -> testi_approvati -> prova_visuale_approvata -> rendering -> qa -> consegnato
```

Non saltare stati e non modificare direttamente `workflow_state` o `workflow_receipts`. Ogni invocazione usa stato e revisione attesi come controllo compare-and-swap, richiede la stessa cartella di sessione dell'editor, acquisisce nell'ordine il lock del manifest e quello della transazione, rifiuta feedback durevoli ancora pendenti, rivalida l'evidenza e scrive manifest e ricevuta atomicamente. Se il comando fallisce, correggere il gate segnalato e ripetere con i valori ancora correnti.

## Diagnosi read-only

Prima di una transizione, dopo un batch o dopo un'interruzione, ottenere una fotografia coerente senza leggere a mano manifest e file di sessione:

```bash
<python> <skill>/scripts/carousel_status.py "<manifest.json>" \
  --session-dir "<session-dir>"
```

Il JSON espone schema, revisione, stato, checkpoint, proof corrente, fingerprint, feedback pendente, output attesi e `next_action`. Se `next_action.command` è presente può essere eseguito dopo aver verificato gli eventuali file evidenza richiesti; l'esito dello status non sostituisce i gate fail-closed di apply, advance o export. Senza `--session-dir` la validazione è soltanto statica e `feedback_pending` resta `null`.

## Transizioni

Per i due checkpoint di approvazione usare normalmente il batch durevole dell'editor:

```bash
<python> <skill>/scripts/process_review.py "<manifest.json>" "<feedback-path>" \
  --session-dir "<session-dir>"
```

Lo script applica il batch e avanza soltanto `bozza -> testi_approvati` oppure `testi_approvati -> prova_visuale_approvata` quando `action: approve` e i gate del checkpoint passano. Un batch `feedback` non avanza. `approval_blocked` lascia lo stato invariato e include lo status da diagnosticare. `apply_review.py` resta disponibile per recovery mirati, ma nel percorso normale non va seguito manualmente da status e advance.

Dopo l'approvazione editoriale, se `cover_mode` è `generated` o `provided`, collegare l'asset con `attach_cover_asset.py` e la revisione corrente. L'operazione è ammessa soltanto in `testi_approvati`, usa il canale append-only della sessione, conserva la ricevuta editoriale e invalida la proof. Non modificare i campi della cover a mano.

Usare percorsi assoluti e sostituire `N` con la `revision` corrente:

```bash
<python> <skill>/scripts/advance_workflow.py "<manifest.json>" \
  --session-dir "<session-dir>" \
  --expected-state bozza --expected-revision N --to testi_approvati

<python> <skill>/scripts/advance_workflow.py "<manifest.json>" \
  --session-dir "<session-dir>" \
  --expected-state testi_approvati --expected-revision N \
  --to prova_visuale_approvata

<python> <skill>/scripts/advance_workflow.py "<manifest.json>" \
  --session-dir "<session-dir>" \
  --expected-state prova_visuale_approvata --expected-revision N --to rendering

<python> <skill>/scripts/advance_workflow.py "<manifest.json>" \
  --session-dir "<session-dir>" \
  --expected-state rendering --expected-revision N --to qa \
  --render-result "<render-result.json>"

<python> <skill>/scripts/advance_workflow.py "<manifest.json>" \
  --session-dir "<session-dir>" \
  --expected-state qa --expected-revision N --to consegnato \
  --render-result "<render-result.json>" \
  --qa-report "<qa-report.json>"
```

Dopo l'export e l'ispezione, preferire il wrapper unico per le ultime due transizioni:

```bash
<python> <skill>/scripts/finalize_delivery.py "<manifest.json>" \
  --session-dir "<session-dir>" \
  --render-result "<render-result.json>" \
  --qa-report "<qa-report.json>"
```

Se parte da `rendering`, il wrapper valida il risultato e avanza a `qa`, poi valida il report e avanza a `consegnato`. Se il secondo gate fallisce, conserva correttamente `qa` e la ricevuta già valida.

I gate sono cumulativi:

- `bozza -> testi_approvati`: batch `approve` applicato alla revisione corrente, stage `profile_text`, digest del feedback valido e zero commenti pendenti;
- `testi_approvati -> prova_visuale_approvata`: batch `approve` allo stage `visual_proof`, proof e fingerprint correnti, Chromium attestato, produttore locale e zero commenti pendenti; il campione visto e gli avvisi visuali restano consultivi;
- `prova_visuale_approvata -> rendering`: proof ancora corrente e `production.expected_outputs` non vuoto. Nel renderer locale sono ammessi `pdf`, `png` e `contact_sheet` (`contact-sheet` è alias); il PDF è obbligatorio;
- `rendering -> qa`: `render-result` corrente e artefatti esistenti con digest SHA-256 coincidenti;
- `qa -> consegnato`: lo stesso `render-result` già legato alla ricevuta, report QA positivo e gli stessi artefatti ancora presenti.

Qualunque modifica a copy, ordine, profilo, sistema, logo, asset o composizione può cambiare revisione o fingerprint e invalidare la proof. `apply_review.py` non avanza mai: una correzione editoriale o una nota non classificabile riapre atomicamente `bozza` e azzera la catena; una modifica esclusivamente a sistema visivo, logo, cover o enfasi tipografica riapre o mantiene `testi_approvati` e conserva soltanto la ricevuta reale `bozza -> testi_approvati`. Una modifica alle sole enfasi non rende stale alt text o trascrizione. Gli asset della cover possono essere collegati dopo l'approvazione dei testi soltanto tramite `attach_cover_asset.py`. Dopo un uso diretto di `apply_review.py` per recovery, rieseguire `carousel_status.py` e usare la revisione corrente restituita, non quella precedente al batch. Ripartire dal checkpoint risultante e non ricostruire le ricevute a mano.

Un batch con `approval_scope: profile_text_and_visual` rappresenta un solo consenso esplicito su testi e preview definitiva. `process_review.py` deve comunque eseguire due transizioni consecutive e aggiungere due ricevute, prima `bozza -> testi_approvati` e poi `testi_approvati -> prova_visuale_approvata`. Non comprimere il ledger e non avanzare automaticamente a `rendering`.

## Risultato di export

Durante lo stato `rendering`, eseguire l'export con `--result-json` come descritto in [production-qa.md](production-qa.md#invocazione-local-editor). L'esportatore pubblica il JSON nello stesso gruppo coordinato di PDF, directory PNG e contact sheet richiesti. Il risultato usa `result_schema: carousel-builder-export-v1` e lega:

- revisione, stato `rendering`, `render_fingerprint`, contratto e browser della proof;
- conteggio e dimensioni delle slide;
- parità esatta anteprima-produzione, sessione live e approvazione;
- un record `{kind, path, sha256}` per ogni artefatto dichiarato.

I percorsi degli artefatti sono assoluti. `artifact_sha256` deve coprire esattamente `production.expected_outputs`: un PDF, un PNG per slide e una contact sheet quando dichiarati. Il `result-json` non include il proprio digest per evitare un riferimento circolare. Non scriverlo o correggerlo manualmente.

## Report QA

Creare `qa-report.json` dopo aver verificato struttura, leggibilità dei file, digest e corrispondenza degli artefatti secondo [production-qa.md](production-qa.md). La revisione umana è consigliata ma consultiva; non impostare comunque un controllo tecnico a `true` sulla sola base dell'esito dell'esportatore. La forma richiesta è:

```json
{
  "report_schema": "carousel-builder-qa-v1",
  "status": "pass",
  "revision": 4,
  "workflow_state": "qa",
  "render_fingerprint": "<sha256 corrente>",
  "proof_browser": {"engine": "chromium", "major": 151},
  "render_evidence_sha256": "auto",
  "checks": {
    "manifest_content_match": true,
    "slide_count_order": true,
    "dimensions": true,
    "files_open": true,
    "fonts": true,
    "preview_production_parity": true,
    "no_incomplete_outputs": true,
    "automated_all_slides": true,
    "human_sample_review": true
  },
  "human_sample_slide_ids": ["cover", "item-2", "outro"],
  "flagged_slide_ids": [],
  "artifacts": [
    {"kind": "pdf", "path": "/percorso/carousel.pdf", "sha256": "<sha256>"}
  ]
}
```

Usare la revisione, il fingerprint e il browser correnti. `automated_all_slides` attesta che i controlli tecnici deterministici hanno coperto l'intera sequenza ed è bloccante. `fonts` e `human_sample_review` sono advisory: registrarli come `true` o `false` in base a ciò che è stato realmente verificato. Quando l'ispezione umana avviene, `human_sample_slide_ids` elenca gli ID osservati senza duplicati; può restare vuoto. Con `finalize_delivery.py`, lasciare `render_evidence_sha256: "auto"`: dopo `rendering -> qa` il wrapper crea una copia privata e immutata negli altri campi, sostituendo soltanto questo valore con il digest durevole dell'oggetto `render-result`. Se si usa direttamente `advance_workflow.py`, copiare invece quel digest dall'ultima ricevuta. In `artifacts` ripetere l'insieme completo e i digest correnti del risultato di export; l'esempio mostra il solo caso `expected_outputs: ["pdf"]`.

## Ricevute durevoli

Ogni transizione aggiunge in `workflow_receipts` una ricevuta con sole chiavi `from`, `to`, `revision`, `render_fingerprint`, `evidence_sha256` e `advanced_at`. La lista conserva al massimo le ultime cinque ricevute, deve formare una catena continua e terminare nello stato corrente. `advanced_at` include il fuso orario.

La ricevuta dimostra quale evidenza ha autorizzato la transizione; non sostituisce l'ispezione degli artefatti e non rende valido un file successivamente modificato. La CLI ricontrolla i digest reali sia all'ingresso in `qa` sia alla consegna.
