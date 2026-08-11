# Schema del manifest

Salvare il manifest del singolo carosello come JSON UTF-8:

```json
{
  "schema_version": "1.3",
  "source_type": "article",
  "sequence_mode": "narrative",
  "visual_style_system": "editorial-frame",
  "logo_mode": "auto",
  "source_url": "https://example.com/article",
  "target_channels": ["instagram_feed", "linkedin_document"],
  "channel_variants": [],
  "workflow_state": "testi_approvati",
  "revision": 1,
  "production": {
    "mode": "layout",
    "producer": "",
    "supported_style_systems": [],
    "expected_outputs": ["layout"]
  },
  "proof": {
    "slide_ids": ["cover", "item-1", "outro"],
    "style_system_verified": false,
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
    "cover_weight": 800,
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
  "cover_image": "assets/cover-visual.png",
  "cover_image_position": "50% 50%",
  "cover_alt_text": "Descrizione concisa del visuale e del contenuto essenziale della copertina",
  "cover_visual_concepts": ["concetto 1", "concetto 2"],
  "cover_visual_metaphor": "Metafora fisica scelta",
  "cover_visual_prompt": "Prompt usato per l'illustrazione",
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

- `schema_version`: usare `1.3` per i nuovi manifest; accettare `1.2`, `1.1` e versioni precedenti come legacy.
- `source_type`: usare `newsletter`, `article`, `notes` o `verbatim`; accettare `rework` e `social` come alias legacy.
- `sequence_mode`: usare `narrative` per una progressione dipendente dall'ordine o `sectional` per slide autonome.
- `visual_style_system`: selezione opzionale per il singolo carosello. Risolvere nell'ordine: questo campo, `brand.visual_signature.style_system`, `editorial-frame`. Usare solo gli ID di [visual-systems.md](visual-systems.md).
- `logo_mode`: usare `auto` per mostrare la variante approvata adatta al fondo oppure `hidden` per omettere il logo nell'intero carosello. Non controllarlo slide per slide.
- `target_channels`: dichiarare i canali e placement previsti prima della produzione.
- `channel_variants`: registrare soltanto le varianti con rapporto o densità diversi dal master; ciascuna richiede una prova visuale dedicata.
- `workflow_state`: usare `bozza`, `testi_approvati`, `prova_visuale_approvata`, `rendering`, `qa` o `consegnato`.
- `revision`: incrementare quando cambiano testi approvati, profilo, visuale o composizione.
- `production.mode`: usare `renderer`, `adapter` o `layout` secondo il preflight.
- `production.producer`: identificatore del renderer o adapter; può restare vuoto in modalità `layout`.
- `production.supported_style_systems`: ID dei sistemi che il produttore implementa realmente. In modalità `renderer` o `adapter` deve contenere il `visual_style_system` risolto; la sola capacità di applicare palette e font non costituisce supporto.
- `production.expected_outputs`: artefatti dichiarati prima della produzione.
- `proof.slide_ids`: copertina, card più densa e chiusura quando prevista.
- `proof.style_system_verified`: impostare `true` soltanto dopo aver verificato nella prova a 480 px l'assenza degli elementi strutturali sulla copertina e la firma obbligatoria del sistema sulle altre card campione.
- `proof.approved`: impostare `true` soltanto dopo il via libera dell'utente sulla prova visuale; il primo checkpoint su profilo e testi non deve modificarlo. Aggiornare allora `workflow_state` a `prova_visuale_approvata`.
- `proof.render_fingerprint`: salvare il fingerprint SHA-256 candidato calcolato dal server sul copy, sul sistema visivo, sulla modalità del logo e sui byte effettivi di cover, loghi e font. Una prova è approvata soltanto quando questo valore coincide con il fingerprint corrente. Riportare automaticamente `proof.approved` a `false` quando cambiano testi, ordine, profilo, sistema visivo, logo, asset o composizione della prova, registrando la necessità di una nuova approvazione.
- `format`: usare il master 4:5 da 1080×1350, l'export 1440×1800 e la prova obbligatoria a 480 px di larghezza. I campi legacy `width` e `height` continuano a indicare l'export finale.
- `typography`: registrare la scala sul master 1080×1350. I valori nominali sono copertina 112 px con peso 800, sottotitolo di copertina 56 px con peso 500 e interlinea 1.08, titoli sezionali 72 px con peso 800, corpo 64 px con peso 620, interlinea 1.12, spazio aggiuntivo fra frasi `sentence_gap_em: 0.6`, tracking -0.025 em e metadati 26 px. Applicare all'export 1440×1800 un fattore uniforme di 4/3.
- `typography.min_auto_scale`: non usare valori inferiori a `0.92`, equivalenti a una riduzione massima dell'8%.
- `typography.overflow_policy`: usare `error_and_copy_revision`; non ridurre ulteriormente il font quando il testo non entra.
- `cover_title`: obbligatorio.
- `cover_subtitle`: opzionale; inserirlo soltanto se fornito o approvato esplicitamente dall'utente. Il renderer lo presenta nel ruolo `emphasis_italic` risolto.
- `cover_title_italic`: massimo una locuzione esatta contenuta nel titolo e resa nel ruolo corsivo risolto.
- `cover_title_bold`: massimo due unità esatte contenute nel titolo, rese con un peso più forte del carattere `display`.
- Tutti i segmenti `*_italic` usano il ruolo `emphasis_italic` risolto. Accettare `*_serif` come alias legacy; Playfair Display va usato esclusivamente in corsivo.
- `summary` e `outro.body`: ogni frase completa inizia su una nuova riga senza righe vuote. Nel rendering ogni frase diventa un blocco distinto; `body_line_height` governa le righe avvolte all'interno del blocco e `sentence_gap_em` aggiunge spazio dopo ogni blocco tranne l'ultimo. I punti interni a numeri e versioni, per esempio `1.2`, non producono un ritorno a capo; lo stesso vale per le abbreviazioni comuni.
- `source_url`: facoltativo.
- `cover_image`: percorso assoluto o relativo al manifest; vuoto per il fallback.
- `cover_image_position`: posizione CSS del ritaglio.
- `cover_alt_text`: descrizione del visuale e delle informazioni essenziali non già disponibili nella trascrizione.
- `cover_visual_concepts`: massimo tre concetti.
- `cover_visual_metaphor` e `cover_visual_prompt`: metadati di revisione.
- `cover_mode`: usare `generated` solo quando l'immagine della copertina è stata generata, `provided` per un asset fornito dall'utente e `typographic` per una copertina senza immagine. Le slide interne non dipendono da questo campo. Accettare i valori legacy `cover_visual_mode: generative|technical` mappandoli rispettivamente a `generated|provided`.
- `brand`: profilo risolto conforme a [brand-profile.md](brand-profile.md), con ruoli `fonts.display` e `fonts.body`; accettare `fonts.sans` come alias legacy di entrambi.
- `items`: almeno un elemento.
- `items[].id`: identificatore stabile e univoco, usato per prova, ordine di lettura e revisioni.
- `items[].layout`: può essere `editorial`, `statement` o `split`; controlla la composizione, non genera etichette visibili.
- `items[].title`: deve essere vuoto in modalità `narrative`; in modalità `sectional` può contenere un titolo breve.
- `items[].summary`: può essere vuoto solo se esiste il titolo.
- `title_bold`, `title_italic`, `title_underline`, `title_accent`, `summary_bold`, `summary_italic`, `summary_underline`, `summary_accent`: unità esatte e univoche presenti nel testo associato. Nelle card interne con corpo `summary_bold` è proposta di default ma resta facoltativa; la sua assenza non invalida l'approvazione. Una card può usare più trattamenti su parole o locuzioni distinte. `*_italic` richiede un ruolo corsivo reale risolto dal profilo; `*_underline` usa il colore del testo; `*_accent` è un evidenziatore di brand adattato al contrasto della singola slide. Non applicare più stili alla stessa unità e non sovrapporre le selezioni. Accettare i campi `*_serif` dei manifest legacy come alias di `*_italic`.
- `items[].alt_text` e `outro.alt_text`: descrizioni pronte per i canali che supportano testo alternativo; non introdurre informazioni assenti dalla slide.
- `outro`: contiene la copia esatta approvata per il singolo carosello; non copiarne titolo e corpo nel profilo riutilizzabile quando sono generati dalla fonte.
- `outro.eyebrow`: lasciare vuoto salvo richiesta esplicita nel profilo.
- `accessibility.reading_order`: elenca tutti gli ID nell'ordine di fruizione.
- `accessibility.transcript`: conserva tutti i testi approvati e descrive i visuali che aggiungono informazione.

Separare con `\n` ogni frase compiuta senza righe vuote.

Il manifest finale deve contenere testo pulito e campi `*_bold`, `*_italic`, `*_underline` e `*_accent` espliciti. Non lasciare asterischi nei campi testuali.

I manifest legacy privi di stato, revisione, prova, accessibilità o `sequence_mode` restano accettabili. Prima di una nuova produzione inizializzare i campi mancanti senza modificare i testi o il profilo esistenti. Non convertire automaticamente titoli esistenti in modalità narrativa: proporre prima la migrazione editoriale.
