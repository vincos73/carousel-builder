# Onboarding del brand

Usare questo flusso quando non è disponibile un profilo già approvato. Non considerare parole come «prova» o «test» un'autorizzazione a usare automaticamente il tema neutro.

## Neutralità

Trattare fonte e identità visiva come input separati. Non assumere che autore, dominio o logo della fonte siano il brand da applicare.

Non usare memoria, profilo personale o lavori precedenti per precompilare nome, sito, logo, colori, font, firma o CTA. Usare valori specifici soltanto quando l'utente li fornisce nel lavoro corrente o approva un profilo allegato.

## Prima interazione

Se la richiesta è generica, spiegare in massimo cinque punti che Carousel Builder può:

- trasformare URL, articoli, newsletter, note o testi in un carosello verticale 4:5;
- usare un tema neutro, configurare un brand o riutilizzare un profilo JSON;
- definire logo, palette, font, sistema visivo, copertina e chiusura;
- far revisionare tutti i testi prima della produzione;
- produrre artefatti finali quando la sessione lo consente oppure un layout pronto da impaginare.

Se manca la fonte, chiedere soltanto:

> Da quale contenuto vuoi partire? Puoi incollare un URL o un testo, oppure caricare un file.

Se è già allegato un profilo legacy con un'ambiguità bloccante, consentire una seconda domanda breve nella stessa risposta per chiarirla senza aggiungere un ulteriore passaggio.

Se la richiesta contiene già fonte e profilo, brand pack, tema neutro o indicazioni sufficienti, non ripetere l'introduzione estesa.

## Scelta del profilo

Se è già allegato un JSON o un brand pack, validarlo e usarlo senza domande ridondanti. Altrimenti proporre:

1. `Configura il mio brand` (consigliata);
2. `Usa un profilo già salvato` (file JSON oppure brand pack con profilo e asset);
3. `Usa il tema neutro`.

Se l'utente configura il brand, chiedere la fonte dell'identità:

1. `Ricavala dal mio sito` (consigliata quando il sito è rappresentativo);
2. `Carico il brand kit`;
3. `Te la descrivo`.

Il conferimento dell'URL del sito autorizza l'analisi di quel sito. Non recuperare risorse estranee o non approvate.

## Dal sito

- Analizzare soltanto nome, logo disponibile, colori ricorrenti, stile tipografico, firma e CTA osservabili.
- Distinguere elementi verificati e proposte.
- Non spacciare un font simile per il font ufficiale.
- Se logo o font non sono recuperabili in modo affidabile, chiedere il file o proporre un fallback dichiarato.

Usare per impostazione predefinita il percorso rapido: mostrare il profilo ricavato e i testi nella stessa anteprima, usando un solo checkpoint editoriale per approvare entrambi. Passare al percorso guidato se l'utente vuole definire ogni scelta.

## Dal brand kit

- Ispezionare tutti gli asset forniti.
- Identificare le varianti del logo per fondi chiari e scuri.
- Estrarre colori e font soltanto quando dichiarati o verificabili.
- Chiedere solo gli elementi essenziali rimasti ambigui.

Usare il percorso rapido salvo richiesta di configurazione dettagliata.

## Configurazione manuale

Proporre:

1. `Configurazione rapida` (consigliata);
2. `Configurazione guidata`.

### Configurazione rapida

Chiedere di completare in un'unica risposta questo schema, consentendo `Decidi tu` per qualsiasi riga:

```text
Nome, sito e logo:
Colori e tipografia:
Stile delle immagini e composizione:
Slide finale e obiettivo della CTA:
```

Per i valori mancanti proporre default dichiarati, senza inventare dati identificativi. Mostrare nella stessa risposta prima `Anteprima profilo brand` e poi `Anteprima testi`. Concludere con queste azioni: `Approva profilo e testi`, `Modifica il profilo`, `Modifica i testi`, `Passa alla configurazione guidata`. Correzioni e approvazioni separate sono valide, ma il checkpoint si chiude soltanto quando profilo e testi risultano entrambi approvati.

### Configurazione guidata

Procedere per gruppi di massimo tre domande e non richiedere informazioni già ricevute.

#### A: identità mostrata

Chiedere nome, sito/firma/tagline e disponibilità del logo con eventuali varianti. Offrire sempre `Non mostrare alcun brand`.

#### B: colori e sfondo

Chiedere fondi chiari, scuri o alternati; colori principali e accento; abbinamenti da evitare. Accettare nomi comuni, codici HEX o immagini. Se mancano indicazioni, proporre 2-3 palette.

#### C: tipografia

Chiedere il carattere per titoli (`display`) e quello per testi (`body`); possono coincidere. Chiedere separatamente quale corsivo usare per le enfasi: la vera variante italic del carattere principale oppure un secondo carattere corsivo. Verificare la disponibilità del relativo file e non sintetizzare il corsivo. Distinguere una richiesta esatta, come `Lato`, da una richiesta di famiglia, come `tipo Lato`.

- Per un font esatto, usare il file fornito oppure una copia già disponibile e verificata. Se manca, chiedere il file.
- Per una richiesta di famiglia, proporre un sostituto disponibile nominandolo prima della prova visuale.
- Non sostituire mai il font scelto con Inter o con un altro carattere senza dichiararlo e ottenere l'approvazione.
- Se si usa un font di sistema, avvertire che la portabilità richiede il file o un brand pack.
- Se un brand kit dichiara ruoli come display, heading, headline, text, body o copy, preservarli invece di ridurre automaticamente tutto a un solo font.

#### D: sistema visivo, immagini e composizione

Leggere [visual-systems.md](visual-systems.md). Chiedere il sistema visivo, la direzione della copertina, eventuali riferimenti e ciò che va evitato. Se non è disponibile generazione immagini, dichiarare `typographic` come fallback universale e accettare un'immagine fornita.

#### E: chiusura

Chiedere se includere la chiusura, l'obiettivo della CTA e se il testo debba essere fisso o generato dalla fonte. Per impostazione predefinita usare `copy_mode: generate_from_source`.

Nel percorso guidato mostrare e far approvare il profilo prima dei testi.

## Direzione visiva

Quando non emerge una direzione riconoscibile, proporre al massimo:

1. `Editoriale geometrico`: forme pulite e metafore essenziali;
2. `Fotografico`: scene credibili e materiali realistici;
3. `Illustrato o collage`: texture, stratificazione e segno espressivo.

Consentire descrizioni libere come blueprint, disegno a mano, 3D, minimal line art o tecnica mista. Non imitare artisti viventi o brand non autorizzati.

## Anteprima del profilo

Mostrare quattro blocchi:

- `Identità`: nome, logo sui fondi chiari e scuri, firma, sito e tagline;
- `Sistema visivo`: palette, modalità dei fondi, font display e body richiesti, ruolo corsivo effettivamente risolto, font disponibili ed eventuali fallback da approvare;
- `Direzione`: sistema visivo, stile, riferimenti, composizione ed elementi da evitare;
- `Chiusura e stato`: presenza della chiusura, obiettivo, modalità della CTA e valori proposti o incerti.

## Profilo riutilizzabile

Dopo l'approvazione, offrire una volta il salvataggio come `<nome-brand>-carousel-brand.json`.

Il JSON non incorpora file binari. Se il profilo usa logo o font caricati, spiegare che per la piena portabilità serve un brand pack composto da JSON e asset. Non creare il brand pack senza richiesta esplicita.

Non salvare nel profilo il titolo o il corpo di una CTA generata per una fonte specifica. Salvare invece obiettivo, eyebrow e `copy_mode`.
