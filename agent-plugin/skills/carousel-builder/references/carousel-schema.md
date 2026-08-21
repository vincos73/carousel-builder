# Schema del manifest

## Indice

- [Esempio completo](#esempio-completo)
- [Campi principali](#campi-principali)

## Esempio completo

Salvare il manifest del singolo carosello come JSON UTF-8:

```json
{
  "schema_version": "1.4",
  "source_type": "article",
  "sequence_mode": "narrative",
  "visual_style_system": "editorial-frame",
  "logo_mode": "auto",
  "source_url": "https://example.com/article",
  "target_channels": ["instagram_feed", "linkedin_document"],
  "channel_variants": [],
  "workflow_state": "bozza",
  "revision": 1,
  "workflow_receipts": [],
  "production": {
    "mode": "layout",
    "producer": "",
    "supported_style_systems": [],
    "expected_outputs": []
  },
  "proof": {
    "slide_ids": ["cover", "item-1", "outro"],
    "style_system_verified": false,
    "browser": null,
    "approved": false
  },
  "format": {
    "ratio": "4:5",
    "master_width": 1080,
    "master_height": 1350,
    "width": 1440,
    "height": 1800,
    "preview_width": 480,
    "preview_height": 600
  },
  "typography": {
    "cover_px": 112,
    "cover_subtitle_px": 56,
    "section_title_px": 72,
    "body_px": 64,
    "metadata_px": 26,
    "cover_weight": 500,
    "cover_subtitle_weight": 500,
    "section_title_weight": 800,
    "body_weight": 620,
    "body_line_height": 1.12,
    "sentence_gap_em": 0.6,
    "cover_subtitle_line_height": 1.08,
    "body_tracking_em": -0.025,
    "min_auto_scale": 0.92,
    "overflow_policy": "error_and_copy_revision"
  },
  "cover_title": "Titolo breve della copertina",
  "cover_subtitle": "Sottotitolo opzionale approvato dall'utente",
  "cover_title_bold": ["Parola o locuzione importante"],
  "cover_title_italic": ["Frase esatta da rendere in corsivo"],
  "cover_title_underline": [],
  "cover_title_accent": [],
  "cover_image": "",
  "cover_image_position": "50% 50%",
  "cover_alt_text": "",
  "cover_visual_concepts": [],
  "cover_visual_metaphor": "",
  "cover_visual_prompt": "",
  "cover_mode": "typographic",
  "brand": {},
  "items": [
    {
      "id": "item-1",
      "layout": "editorial",
      "title": "",
      "title_bold": [],
      "title_italic": [],
      "title_underline": [],
      "title_accent": [],
      "summary": "Prima frase compiuta.\nSeconda frase compiuta.",
      "summary_bold": ["Concetto decisivo"],
      "summary_accent": ["Concetto completo"],
      "summary_italic": ["Passaggio espressivo"],
      "summary_underline": [],
      "alt_text": "Testo alternativo della slide"
    }
  ],
  "outro": {
    "enabled": true,
    "eyebrow": "",
    "title": "Titolo generato per questa fonte",
    "body": "Testo generato per questa fonte",
    "goal": "comment",
    "alt_text": "Testo alternativo della chiusura"
  },
  "accessibility": {
    "reading_order": ["cover", "item-1", "outro"],
    "transcript": "Trascrizione completa e ordinata del carosello"
  }
}
```

## Campi principali

- `schema_version`: usare `1.4` per i nuovi manifest locali. Accettare `1.3`, `1.2`, `1.1` e versioni precedenti in sola compatibilità legacy; non inventare ricevute per promuoverli. Per usare il workflow attestato, creare o migrare esplicitamente un manifest 1.4 e ripetere i checkpoint reali.
- `source_type`: usare `newsletter`, `article`, `notes` o `verbatim`; accettare `rework` e `social` come alias legacy.
- `sequence_mode`: usare `narrative` per una progressione dipendente dall'ordine o `sectional` per slide autonome.
- `visual_style_system`: selezione opzionale per il singolo carosello. Risolvere nell'ordine: questo campo, `brand.visual_signature.style_system`, `editorial-frame`. Usare solo gli ID di [visual-systems.md](visual-systems.md).
- `logo_mode`: usare `auto` per mostrare la variante approvata adatta al fondo oppure `hidden` per omettere il logo nell'intero carosello. Non controllarlo slide per slide.
- `target_channels`: dichiarare i canali e placement previsti prima della produzione.
- `channel_variants`: registrare soltanto le varianti con rapporto o densità diversi dal master; ciascuna richiede una prova visuale dedicata.
- `workflow_state`: usare `bozza`, `testi_approvati`, `prova_visuale_approvata`, `rendering`, `qa` o `consegnato`. Nel percorso `local-editor` iniziare da `bozza`, usare `scripts/process_review.py` per i due checkpoint di approvazione, `advance_workflow.py` per entrare in produzione e `finalize_delivery.py` per i gate finali secondo [workflow-state.md](workflow-state.md); non modificare il campo a mano. Adapter e `layout` usano il contratto del proprio produttore e non devono simulare le attestazioni locali.
- `revision`: incrementare quando cambiano testi approvati, profilo, visuale o composizione. Una transizione di stato valida non incrementa da sola la revisione.
- `workflow_receipts`: nello schema 1.4 inizializzare come lista vuota in `bozza`. La CLI aggiunge una ricevuta per ogni passaggio; in qualunque stato successivo la lista deve coprire senza salti l'intera catena da `bozza` allo stato corrente, con `from`, `to`, `revision`, `render_fingerprint`, `evidence_sha256` e `advanced_at`. Non crearla o correggerla manualmente. I manifest legacy possono non avere il campo ma non possono essere avanzati dalla CLI 1.4.
- `production.mode`: usare `renderer`, `adapter` o `layout` secondo il preflight.
- `production.producer`: identificatore del renderer o adapter; può restare vuoto in modalità `layout`. Nel percorso `local-editor` deve coincidere con il contratto corrente `approved-preview-dom-v2`; un identificatore diverso richiede il flusso di prova ed export del produttore esterno e non può riusare l'approvazione del renderer locale.
- `production.supported_style_systems`: ID dei sistemi che il produttore implementa realmente. In modalità `renderer` o `adapter` deve contenere il `visual_style_system` risolto; la sola capacità di applicare palette e font non costituisce supporto.
- `production.expected_outputs`: artefatti dichiarati prima della produzione. Per il renderer locale usare una combinazione di `pdf`, `png` e `contact_sheet` (`contact-sheet` resta alias); `pdf` è obbligatorio e il risultato di export deve attestare esattamente il set dichiarato. Non dichiarare `contact_sheet` per default: aggiungerla soltanto se richiesta o utile alla revisione umana.
- `proof.slide_ids`: campione canonico nell'ordine della sequenza: copertina, card interna più densa e chiusura quando prevista. In caso di pari densità scegliere la prima card nell'ordine corrente; dopo eliminazioni, riordini o modifiche al copy ricalcolare il campione e richiedere una nuova prova.
- `proof.style_system_verified`: campo booleano legacy e diagnostico. Può essere `true` quando una persona ha eseguito il controllo visuale tradizionale, ma non certifica la qualità e non blocca approvazione o export.
- `proof.browser`: salvare `{ "engine": "chromium", "major": N }` soltanto insieme all'approvazione visuale, usando la major del browser in cui il campione è stato realmente visto. Il renderer locale esporta con Chromium e richiede la stessa major; una prova aperta in un altro motore deve essere riapprovata in Chromium.
- `proof.approved`: impostare `true` soltanto tramite l'applicazione di un batch che include l'attestazione visuale dopo il via libera dell'utente. Nel percorso ordinario il primo checkpoint su profilo e testi non lo modifica; nel percorso combinato lo stesso batch porta `approval_scope: profile_text_and_visual`, lega la proof e consente a `process_review.py` di registrare in sequenza entrambe le ricevute. Non cambiare lo stato a mano.
- `proof.render_fingerprint`: salvare il fingerprint SHA-256 candidato calcolato dal server sul copy, sul sistema visivo, sulla modalità del logo, sul contratto di produzione/output e sui byte effettivi di HTML, JavaScript, CSS, cover, loghi e font. Il checkpoint corrente e `production.supported_style_systems` sono metadati di controllo, non pixel, e non entrano nel digest; stato base e validazione del produttore restano gate separati. Una prova è approvata soltanto quando questo valore coincide con il fingerprint corrente. Riportare automaticamente `proof.approved` a `false`, azzerare il campo diagnostico `proof.style_system_verified` e rimuovere `proof.browser` quando cambiano testi, ordine, profilo, sistema visivo, logo, output attesi, asset o composizione della prova.
- `format`: usare il master 4:5 da 1080×1350, l'export 1440×1800 e la prova obbligatoria a 480 px di larghezza. I campi legacy `width` e `height` continuano a indicare l'export finale.
- `typography`: registrare la scala sul master 1080×1350. I valori nominali sono copertina 112 px con peso 800, sottotitolo di copertina 56 px con peso 500 e interlinea 1.08, titoli sezionali 72 px con peso 800, corpo 64 px con peso 620, interlinea 1.12, spazio aggiuntivo fra frasi `sentence_gap_em: 0.6`, tracking -0.025 em e metadati 26 px. Applicare all'export 1440×1800 un fattore uniforme di 4/3.
- `typography.min_auto_scale`: non usare valori inferiori a `0.92`, equivalenti a una riduzione massima dell'8%.
- `typography.overflow_policy`: mantenere `error_and_copy_revision` come segnale compatibile del renderer. Nell'editor l'overflow è un avviso consultivo: non ridurre silenziosamente il font e non riscrivere il testo dell'utente.
- `cover_title`: obbligatorio.
- `cover_subtitle`: opzionale; inserirlo soltanto se fornito o approvato esplicitamente dall'utente. Il renderer lo presenta nel ruolo `emphasis_italic` risolto.
- `cover_title_italic`: massimo una locuzione esatta contenuta nel titolo e resa nel ruolo corsivo risolto.
- `cover_title_bold`: massimo due unità esatte contenute nel titolo, rese con un peso più forte del carattere `display`.
- Tutti i segmenti `*_italic` usano il ruolo `emphasis_italic` risolto. Accettare `*_serif` come alias legacy; nel profilo neutro usare la variante reale Times New Roman Italic di sistema.
- `summary` e `outro.body`: ogni frase completa inizia su una nuova riga senza righe vuote. Nel rendering ogni frase diventa un blocco distinto; `body_line_height` governa le righe avvolte all'interno del blocco e `sentence_gap_em` aggiunge spazio dopo ogni blocco tranne l'ultimo. I punti interni a numeri e versioni, per esempio `1.2`, non producono un ritorno a capo; lo stesso vale per le abbreviazioni comuni.
- `source_url`: facoltativo.
- `cover_image`: percorso assoluto o relativo al manifest; vuoto per `typographic` e durante l'intenzione `generated` non ancora prodotta. Nel percorso locale aggiungerlo dopo l'approvazione dei testi soltanto tramite `attach_cover_asset.py`.
- `cover_image_position`: posizione CSS del ritaglio.
- `cover_alt_text`: descrizione del visuale e delle informazioni essenziali non già disponibili nella trascrizione.
- `cover_visual_concepts`: massimo tre concetti.
- `cover_visual_metaphor` e `cover_visual_prompt`: metadati di revisione.
- `cover_mode`: usare `generated` quando l'utente richiede una copertina da generare, `provided` per un asset dell'utente e `typographic` per una copertina senza immagine. Prima dell'approvazione visuale `generated` può rappresentare un'intenzione ancora priva di `cover_image`; la proof non è approvabile finché l'asset non è disponibile. `typographic` è il default in assenza di una scelta esplicita. In `generated` e `provided` il renderer usa una composizione split deterministica con testo a sinistra e immagine verticale a destra, senza overlay o trasparenza. Le slide interne non dipendono da questo campo. Accettare i valori legacy `cover_visual_mode: generative|technical` mappandoli rispettivamente a `generated|provided`.
- `brand`: profilo risolto conforme a [brand-profile.md](brand-profile.md), con ruoli `fonts.display` e `fonts.body`; accettare `fonts.sans` come alias legacy di entrambi.
- `items`: almeno un elemento.
- `items[].id`: identificatore stabile e univoco di 1-64 caratteri formato da lettere, numeri, trattino o underscore, usato per prova, ordine di lettura e revisioni. `cover` e `outro` sono riservati.
- `items[].layout`: può essere `editorial`, `statement` o `split`; controlla la composizione, non genera etichette visibili.
- `items[].title`: deve essere vuoto in modalità `narrative`; in modalità `sectional` può contenere un titolo breve.
- `items[].summary`: può essere vuoto solo se esiste il titolo.
- `title_bold`, `title_italic`, `title_underline`, `title_accent`, `summary_bold`, `summary_italic`, `summary_underline`, `summary_accent`: unità esatte presenti nel testo associato. Nelle card interne con corpo `summary_bold` è proposta di default ma resta facoltativa; la sua assenza non invalida l'approvazione. Una card può usare più trattamenti su parole o locuzioni distinte. `*_italic` richiede un ruolo corsivo reale risolto dal profilo; `*_underline` usa il colore del testo; `*_accent` è un evidenziatore di brand adattato al contrasto della singola slide. Non applicare più stili allo stesso intervallo e non sovrapporre le selezioni. Quando una locuzione ricorre, usare i campi `*_ranges` per identificare l'occorrenza esatta. Accettare i campi `*_serif` dei manifest legacy come alias di `*_italic`.
- I campi opzionali `*_bold_ranges`, `*_italic_ranges`, `*_underline_ranges` e `*_accent_ranges` conservano, per ogni enfasi, `{ "text": "...", "start": N, "end": N }`. Servono quando la stessa locuzione compare più volte: l'enfasi deve applicarsi solo all'intervallo selezionato, senza chiedere di rendere unica la parola.
- `items[].alt_text` e `outro.alt_text`: descrizioni pronte per i canali che supportano testo alternativo; non introdurre informazioni assenti dalla slide.
- `outro`: contiene la copia esatta approvata per il singolo carosello; non copiarne titolo e corpo nel profilo riutilizzabile quando sono generati dalla fonte.
- `outro.eyebrow`: lasciare vuoto salvo richiesta esplicita nel profilo.
- `accessibility.reading_order`: elenca tutti gli ID nell'ordine di fruizione.
- `accessibility.transcript`: conserva tutti i testi approvati e descrive i visuali che aggiungono informazione.

Separare con `\n` ogni frase compiuta senza righe vuote.

Il manifest finale deve contenere testo pulito e campi `*_bold`, `*_italic`, `*_underline` e `*_accent` espliciti. Non lasciare asterischi nei campi testuali.

I manifest legacy privi di stato, revisione, prova, accessibilità o `sequence_mode` restano accettabili. Prima di una nuova produzione inizializzare i campi mancanti senza modificare i testi o il profilo esistenti. Non convertire automaticamente titoli esistenti in modalità narrativa: proporre prima la migrazione editoriale.
