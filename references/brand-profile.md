# Profilo di brand

Usare per i nuovi profili questo schema:

```json
{
  "profile_type": "carousel-brand",
  "schema_version": "1.1",
  "name": "Studio Example",
  "website": "example.com",
  "signature": "Studio Example",
  "tagline": "Ideas made clear",
  "logos": {
    "on_light": "assets/logo-dark.svg",
    "on_dark": "assets/logo-light.svg"
  },
  "fonts": {
    "display": { "family": "Brand Display", "file": "assets/BrandDisplay.ttf", "source": "uploaded" },
    "body": { "family": "Brand Text", "file": "assets/BrandText.ttf", "source": "uploaded" },
    "body_italic": { "family": "Brand Text", "file": "assets/BrandTextItalic.ttf", "source": "uploaded" },
    "emphasis_italic": { "family": "Brand Text", "file": "assets/BrandTextItalic.ttf", "source": "uploaded" }
  },
  "typography": {
    "cover_px": 112,
    "cover_subtitle_px": 56,
    "section_title_px": 72,
    "body_px": 64,
    "cover_weight": 500,
    "cover_subtitle_weight": 500,
    "section_title_weight": 800,
    "body_weight": 620,
    "body_line_height": 1.12,
    "sentence_gap_em": 0.6,
    "cover_subtitle_line_height": 1.08,
    "body_tracking_em": -0.025,
    "metadata_px": 26
  },
  "palette": {
    "surface_mode": "alternating",
    "background_light": "#F5F1E8",
    "background_dark": "#172033",
    "text_on_light": "#172033",
    "text_on_dark": "#FFFFFF",
    "accent": "#C65A3A"
  },
  "visual_direction": {
    "mode": "editorial-geometric",
    "description": "Metafore visive essenziali, forme nette e texture leggere",
    "references": [],
    "avoid": ["robot umanoidi", "circuiti generici"],
    "internal_slides": "clean_typographic"
  },
  "visual_signature": {
    "style_system": "editorial-frame"
  },
  "outro": {
    "enabled": true,
    "goal": "comment",
    "copy_mode": "generate_from_source",
    "eyebrow": "",
    "fixed_title": "",
    "fixed_body": ""
  }
}
```

## Regole

- Usare `profile_type: carousel-brand` e `schema_version: 1.1` per i nuovi profili.
- Consentire `surface_mode`: `light`, `dark` o `alternating`.
- Usare `logos.on_light` sui fondi chiari e `logos.on_dark` sui fondi scuri.
- Accettare TTF, OTF, WOFF e WOFF2. Usare `source`: `uploaded`, `bundled`, `system` o `fallback`.
- Usare `display` per copertina e titoli e `body` per testi, CTA e metadati. Possono indicare la stessa famiglia oppure due famiglie diverse. Verificarne il caricamento effettivo prima della prova visuale.
- Trattare `emphasis_italic` come ruolo espressivo opzionale per sottotitolo di copertina ed enfasi semantiche. Può coincidere con `body_italic`, cioè la vera variante corsiva del carattere principale, oppure indicare un secondo carattere corsivo approvato.
- Risolvere il ruolo corsivo nell'ordine `emphasis_italic`, `body_italic`, `serif_italic` legacy. Non derivare un corsivo inclinando artificialmente il file regular e non usarlo come sostituto del ruolo `body`.
- Se l'utente richiede un font esatto e il file non è disponibile, chiedere il file. Se indica soltanto una famiglia o un tono, proporre un sostituto disponibile e attenderne l'approvazione.
- Il profilo neutro usa Arial di sistema per `display` e `body` e preferisce la vera variante Arial Italic di sistema per `emphasis_italic`; se non è disponibile può usare Times New Roman Italic di sistema. Il browser verifica la variante locale prima della prova e mostra il fallback effettivo se mancano.
- Non incorporare font nel pacchetto della skill. Un profilo personalizzato può ancora usare file forniti dall'utente; i font di sistema restano portabili soltanto dove la stessa famiglia è installata.
- Un font con `source: system` può essere usato dopo verifica locale, dichiarando che non è portabile senza il relativo file.
- Usare la scala tipografica nominale indicata nel profilo. Scostamenti richiedono approvazione e restano soggetti al limite di riduzione dell'8%.
- Usare `sentence_gap_em: 0.6` come spazio aggiuntivo fra blocchi-frase nelle card. Non incorporare questa distanza in `body_line_height` e non sostituirla con righe vuote nel testo.
- Accettare per `visual_direction.mode`: `editorial-geometric`, `photographic`, `illustrated-collage`, `hand-drawn`, `3d` o `custom`.
- Trattare `visual_direction.description` come istruzione primaria.
- Usare riferimenti soltanto se forniti o approvati.
- Applicare `visual_direction.avoid` alla generazione e alla revisione.
- Usare `visual_direction.internal_slides: clean_typographic` come impostazione predefinita: un solo visuale in copertina e slide interne prive di illustrazioni decorative. Un valore diverso richiede una scelta esplicita e una prova visuale aggiornata.
- Usare `visual_signature.style_system` con uno degli ID definiti in [visual-systems.md](visual-systems.md). Il sistema determina la grammatica delle card; font, palette, logo, firma e sito restano quelli del profilo. Il manifest può selezionare un override per il singolo carosello.
- Verificare almeno 4.5:1 tra testo normale e sfondo e almeno 3:1 per testo grande. Segnalare un contrasto insufficiente anziché alterare silenziosamente i colori identificativi.
- Non inventare dati identificativi mancanti.
- Consentire un profilo personalizzato senza identità mostrata, lasciando vuoti nome, sito, firma, tagline e logo.

## Chiusura

Usare `copy_mode: generate_from_source` per generare titolo e corpo coerenti con la fonte corrente e con `goal`. Lasciare `eyebrow` vuoto salvo richiesta esplicita. Salvare nel profilo soltanto la strategia riutilizzabile.

Usare `copy_mode: fixed` solo quando l'utente vuole deliberatamente riutilizzare `fixed_title` e `fixed_body` in tutti i caroselli.

Le copie esatte generate per il singolo carosello appartengono al manifest, non al profilo.

## Portabilità degli asset

Il JSON non incorpora logo o font. Risolvere i percorsi relativi rispetto al JSON o al manifest che incorpora il profilo.

Per i logo accettare una stringa oppure un oggetto con `file` e `preview_file`. Il master può essere SVG; l'anteprima locale deve usare un PNG, JPG o WebP dichiarato. Quando il valore è una stringa SVG e nella stessa cartella esiste un PNG omonimo, l'editor può usare quel PNG come derivato di anteprima, dichiarando la sostituzione nell'interfaccia e senza modificare il master.

Se un asset referenziato manca:

1. non sostituirlo silenziosamente con un asset fittizio;
2. chiedere il file oppure proporre un fallback dichiarato;
3. offrire un brand pack con JSON e asset quando l'utente chiede portabilità completa.

## Compatibilità con profili precedenti

Accettare profili senza `schema_version` come legacy:

- mappare `logo_light` a `logos.on_light` e `logo_dark` a `logos.on_dark` secondo il comportamento storico;
- convertire i font espressi come stringhe in oggetti con `source` coerente;
- mappare `fonts.sans` sia a `display` sia a `body` quando i nuovi ruoli non sono presenti;
- mappare `fonts.serif` a `serif_italic` quando il nuovo ruolo non è presente;
- usare `fonts.serif_italic` come alias legacy di `fonts.emphasis_italic` quando i nuovi ruoli corsivi non sono presenti;
- convertire `palettes` nella nuova `palette`, chiedendo chiarimento solo se esistono valori incompatibili;
- migrare `visual_system` a `visual_signature.style_system` quando presente;
- se `outro` contiene titolo o corpo ma non `copy_mode`, chiedere se siano testi fissi oppure specifici della vecchia fonte; non riutilizzarli automaticamente.

## Profilo neutro

Usarlo soltanto dopo scelta esplicita:

- `name`: `Editorial Carousel`;
- nessun logo, sito, firma o tagline;
- Arial di sistema nei ruoli `display` e `body`, Arial Italic di sistema come `emphasis_italic` quando disponibile, altrimenti Times New Roman Italic di sistema;
- `surface_mode: alternating` con `background_light: #F8F7F4`, `background_dark: #2D2E2F`, `text_on_light: #2D2E2F`, `text_on_dark: #FFFFFF` e accento melanzana `#6B3F5D`;
- direzione `editorial-geometric`;
- `visual_signature.style_system: editorial-frame`;
- chiusura generata dalla fonte per `newsletter` e `article`.

Non salvarlo come brand dell'utente.
