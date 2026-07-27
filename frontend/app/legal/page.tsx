import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Impressum & Datenschutz",
  description: "Anbieterkennzeichnung und Datenschutzhinweise.",
  robots: { index: false },
};

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

/**
 * Impressum (§5 DDG) and privacy notice.
 *
 * The Impressum block below is a PLACEHOLDER and must be completed before the site
 * is publicly reachable -- it has to carry your real, verifiable contact details.
 * The privacy section is filled in, because it describes what this codebase
 * actually does; keep it in step if the processing ever changes.
 */
export default function LegalPage() {
  return (
    <div className="prose py-8">
      <h1 className="font-display text-3xl">Impressum</h1>

      <p className="border border-rule bg-raised p-4 font-mono text-sm not-prose">
        TODO before going public: replace this block with your Anbieterkennzeichnung
        under §5 DDG — name, Anschrift, E-Mail, and (if applicable) USt-IdNr. and
        Verantwortlicher i.S.d. §18 Abs. 2 MStV.
      </p>

      <h2>Datenschutzerklärung</h2>

      <h3>Verantwortlicher</h3>
      <p>Siehe Impressum.</p>

      <h3>Was verarbeitet wird</h3>
      <p>
        Diese Seite setzt <strong>keine Cookies</strong>, bindet keine Dienste Dritter
        ein und speichert nichts auf Ihrem Gerät. Es gibt kein Nutzerkonto und keine
        Kommentarfunktion.
      </p>
      <p>
        Beim Abruf einer Seite verarbeitet der Server technisch notwendig Ihre
        IP-Adresse und die User-Agent-Kennung Ihres Browsers. Diese Daten werden für
        die Auslieferung der Seite benötigt und nicht dauerhaft mit dem Seitenabruf
        verknüpft gespeichert.
      </p>

      <h3>Aufrufzähler</h3>
      <p>
        Für jeden Beitrag wird gezählt, wie oft er aufgerufen wurde. Dazu wird aus
        IP-Adresse, User-Agent und einem täglich wechselnden, geheimen Zufallswert ein
        Hash gebildet, der ausschließlich kurzzeitig im Arbeitsspeicher vorgehalten
        wird, um Mehrfachzählungen desselben Abrufs zu vermeiden. Der Hash wird nicht
        dauerhaft gespeichert und ist nach dem täglichen Wechsel des Zufallswerts nicht
        mehr zuordenbar. Gespeichert wird nur eine Zahl je Beitrag und Tag.
      </p>
      <p>
        Rechtsgrundlage ist Art. 6 Abs. 1 lit. f DSGVO. Das berechtigte Interesse
        besteht darin, die Reichweite der eigenen Beiträge in aggregierter Form
        einschätzen zu können. Da keine Informationen auf Ihrem Endgerät gespeichert
        oder ausgelesen werden, ist keine Einwilligung nach §25 TDDDG erforderlich.
      </p>

      <h3>Server-Logfiles</h3>
      <p>
        Der Webserver protokolliert Zugriffe (Zeitpunkt, angeforderte Adresse,
        Statuscode, IP-Adresse) zur Abwehr von Missbrauch und zur Fehlersuche.
        Rechtsgrundlage ist Art. 6 Abs. 1 lit. f DSGVO. Die Logs werden nach kurzer
        Zeit automatisch gelöscht.
      </p>

      <h3>Weitergabe</h3>
      <p>
        Es findet keine Weitergabe an Dritte statt. Beiträge werden von mir manuell im
        Fediverse veröffentlicht; dabei wird lediglich der öffentliche Link zu dieser
        Seite geteilt, keine Besucherdaten.
      </p>

      <h3>Ihre Rechte</h3>
      <p>
        Sie haben das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung der
        Verarbeitung, Datenübertragbarkeit und Widerspruch sowie ein Beschwerderecht
        bei einer Aufsichtsbehörde. Kontakt: siehe Impressum.
      </p>

      <h3>Hinweis zur Buchdatenquelle</h3>
      <p>
        Titel-, Autoren- und Coverangaben stammen aus meiner privaten
        Audiobookshelf-Instanz und werden serverseitig gespiegelt. Beim Aufruf dieser
        Seite besteht keine Verbindung zu dieser Instanz.
      </p>

      <p className="text-sm text-muted">
        Diese Seite: <a href={SITE_URL}>{SITE_URL}</a>
      </p>
    </div>
  );
}
