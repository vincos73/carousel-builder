# Visuale di copertina

Separare intenzione e produzione. Nella prima revisione registrare `typographic` per impostazione predefinita, `generated` se l'utente chiede una cover illustrata o seleziona `Con visuale`, oppure `provided` per un asset dell'utente. Questa scelta non blocca l'approvazione editoriale e non autorizza ancora il rendering dell'immagine. Generare, acquisire e collegare l'asset soltanto dopo l'approvazione di profilo e testi e prima della prova visuale.

Derivare soggetto, scena e metafora dalla fonte corrente; derivare stile, tecnica, palette e tono da `brand.visual_direction` e dagli altri campi del profilo. Per impostazione predefinita non generare illustrazioni decorative per le slide interne; restano consentiti gli SVG strutturali del sistema visivo.

## Composizione split

Una copertina con visuale usa sempre una struttura deterministica, indipendente dal sistema delle card interne:

- titolo, eventuale sottotitolo e firma occupano la colonna sinistra;
- l'immagine occupa una colonna verticale continua a destra, circa il 45% della larghezza;
- testo e immagine non si sovrappongono;
- non usare opacità, velature, gradienti di compensazione o testo sopra l'immagine;
- tenere il soggetto principale dentro una fascia centrale compatibile con il crop stretto della colonna destra.

La trasparenza non è un fallback: rende contrasto e leggibilità dipendenti dai singoli pixel dell'immagine e moltiplica le verifiche. Se lo split non sostiene il titolo, accorciare il copy entro i limiti approvati o usare `typographic`; non sovrapporre il testo al visuale.

## Estrazione

1. Elencare i concetti presenti nelle slide.
2. Ordinarli per centralità e capacità distintiva.
3. Selezionarne massimo tre in `cover_visual_concepts`.
4. Tradurre la relazione tra i concetti in una scena, un oggetto o un sistema fisico e salvarla in `cover_visual_metaphor`.
5. Evitare di riutilizzare automaticamente metafore di lavori precedenti.

Tenere separate le decisioni: la fonte determina cosa rappresentare; il profilo determina come rappresentarlo. Non cambiare concetti o metafora per adattarli a uno stile preferito.

Per newsletter eterogenee, rappresentare il tema dominante o il filo comune; evitare collage. Per articoli, rappresentare tesi, tensione o meccanismo causale. Per note, rappresentare la trasformazione principale senza aggiungere concetti.

## Prompt

Preparare il prompt solo in modalità `generated`. In modalità `provided`, verificare che l'asset supporti metafora e crop verticale. In modalità `typographic`, tradurre metafora e composizione in gerarchia testuale, superfici e contrasto, senza inventare un'immagine e senza aggiungere cornice, costellazione o indice modulare.

Costruire il prompt con:

```text
Uso: immagine editoriale verticale per la colonna destra della copertina di un carosello 4:5.
Tema centrale: [cover_title].
Concetti selezionati: [cover_visual_concepts].
Metafora: [cover_visual_metaphor].
Scena e soggetti: [elementi specifici della fonte].
Direzione visiva: [brand.visual_direction.mode e brand.visual_direction.description].
Riferimenti approvati: [brand.visual_direction.references, se presenti].
Palette: [colori del profilo].
Composizione: soggetto principale nella fascia centrale; leggibile in un crop verticale stretto largo circa il 45% della card; nessun contenuto destinato alla metà sinistra.
Vincoli: [brand.visual_direction.avoid]; nessun testo, lettera, numero, logo, watermark, interfaccia, cornice, mockup di slide, trasparenza o gradiente per ospitare testo.
```

## Regole

- Preferire una scena unificante a un collage di simboli.
- Rispettare la modalità scelta: non trasformare automaticamente uno stile fotografico in illustrazione o uno stile materico in grafica geometrica.
- Mantenere una sola tecnica visiva. Se l'utente richiede visuali anche nelle slide interne, non mescolare una copertina materica o illustrata con doodle SVG generici; produrre una nuova prova che dimostri coerenza tra le card interessate.
- Se la direzione visiva manca nel profilo personalizzato, chiederla prima di generare. Per il profilo neutro usare `editorial-geometric`.
- Evitare robot, cervelli luminosi e circuiti generici se non necessari alla tesi.
- Non imitare lo stile di artisti viventi o brand non autorizzati.
- In modalità `generated` o `provided`, preferire un'immagine verticale di almeno 1440×1800. Se lo strumento produce un rapporto diverso, mantenere soggetti ed elementi essenziali nella fascia centrale che resterà visibile nel crop della colonna destra.
- Salvare un'immagine usata accanto al manifest o in `assets/`, mai nella cartella finale che il renderer ricrea.
- Nel percorso locale collegare o sostituire l'asset soltanto nello stato `testi_approvati` con `scripts/attach_cover_asset.py`, passando revisione attesa, modalità, alt text, crop e metadati. Lo script copia l'immagine in `assets/`, registra un batch durevole, conserva la ricevuta editoriale e invalida la sola prova visuale. Non modificare direttamente `cover_image`, hash o ricevute.
- Se i testi cambiano in modo da invalidare la metafora, applicare prima la correzione editoriale; il workflow riapre `bozza`. Approvare nuovamente i testi e generare un visuale coerente con la nuova revisione.
- Dopo il rendering di un'immagine, correggere prima `cover_image_position`; rigenerarla o richiedere un altro asset solo se il problema è compositivo.

## Approvazione

Inserire il visuale nella prova con copertina, card più densa e chiusura. Non avviare il rendering completo prima dell'approvazione della prova. Se l'utente cambia metafora, stile, composizione o crop, aggiornare il visuale e mostrare una nuova prova senza modificare i testi approvati.

Se la sessione non può generare immagini, usare la copertina `typographic` o un asset `provided`. Il segnaposto dell'editor documenta soltanto l'intenzione e non può superare l'approvazione visuale. Se non è disponibile un renderer, mostrare metafora, composizione, palette e ingombri come layout dichiarato. Non presentare una descrizione o un segnaposto come immagine prodotta.
