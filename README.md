<p align="center">
  <img src="assets/icon.svg" width="80" alt="Icona Carousel Builder">
</p>

# Carousel Builder

Skill per Codex che trasforma URL, articoli, newsletter, note e testi in caroselli editoriali verticali 4:5 per Instagram, LinkedIn e altri canali social.

La versione **1.7.0** è disponibile per il test pubblico.

## Cosa fa

- legge e sintetizza una fonte senza aggiungere informazioni estranee;
- configura un'identità visiva da sito, brand kit, descrizione manuale o profilo JSON;
- distingue tra sequenza narrativa e sequenza sezionale;
- permette di approvare profilo e testi prima della produzione grafica;
- genera una prova visuale con copertina, slide più densa e chiusura;
- produce PNG, PDF o un layout dettagliato, secondo gli strumenti disponibili;
- controlla leggibilità, contrasto, font, ritagli e corrispondenza con i testi approvati.

## Flusso

1. **Fonte**: URL, testo, note o file.
2. **Brand**: configurazione, profilo salvato oppure tema neutro.
3. **Anteprima editoriale**: profilo e testi completi da approvare.
4. **Prova visuale**: copertina, slide più densa e chiusura.
5. **Produzione**: sequenza completa soltanto dopo la seconda approvazione.
6. **Controllo finale**: verifica di tutti gli artefatti prodotti.

## Modalità editoriali

### Narrativa

Per articoli e contenuti che sviluppano un'unica tesi. Le slide interne non hanno titoli, numerazioni o etichette tecniche. La sequenza costruisce un flusso continuo.

### Sezionale

Per newsletter, raccolte e contenuti composti da sezioni autonome. Ogni slide può avere un titolo quando deve essere comprensibile anche isolata.

## Sistema visivo

- master 4:5: **1080×1350 px**;
- esportazione ad alta definizione: **1440×1800 px**;
- prova obbligatoria a **480×600 px**;
- adattamento tipografico automatico massimo: **8%**;
- visuale generato in copertina, con slide interne pulite per impostazione predefinita;
- font e pesi derivati dal profilo approvato, senza imporre un carattere fisso.

## Installazione dalla Release

1. Scarica `carousel-builder-1.7.0.zip` dalla sezione **Releases**.
2. Estrai l'archivio mantenendo la cartella principale `carousel-builder`.
3. Copia la cartella in:

   ```text
   ~/.codex/skills/carousel-builder
   ```

4. Apri una nuova attività in Codex e richiama la skill con `$carousel-builder`.

Il file deve risultare disponibile in:

```text
~/.codex/skills/carousel-builder/SKILL.md
```

## Installazione con Git

```bash
git clone https://github.com/vincos73/carousel-builder.git ~/.codex/skills/carousel-builder
```

## Esempi

```text
$carousel-builder Trasforma questo articolo in un carosello: https://example.com/articolo
```

```text
$carousel-builder Crea un carosello a partire da queste note e guidami nella configurazione del brand.
```

```text
$carousel-builder Usa il profilo JSON allegato e prepara prima l'anteprima dei testi.
```

## Principi

- La fonte editoriale e il brand sono input separati.
- Il brand non viene ricavato dalla memoria o dall'identità personale dell'utente.
- I testi vengono approvati prima della prova visuale.
- Il rendering completo richiede una seconda approvazione.
- Il testo non viene ridotto oltre l'8% per forzarlo dentro una slide.
- Logo, sito, firma e font non vengono inventati o sostituiti in modo invisibile.

## Feedback

Questa release è destinata al test. Per segnalare problemi o proporre miglioramenti, apri una Issue indicando:

- tipo di fonte utilizzata;
- modalità narrativa o sezionale;
- passaggio in cui si è verificato il problema;
- risultato atteso e risultato ottenuto;
- eventuali immagini della prova, senza dati riservati.

## Licenza

Da definire.

## Autore

[Vincenzo Cosenza](https://github.com/vincos73)

