import type { Metadata } from "next";

import { impressum, missingRequired } from "@/lib/impressum";

export const metadata: Metadata = {
  title: "Impressum & Datenschutz",
  description: "Anbieterkennzeichnung und Datenschutzhinweise.",
  robots: { index: false },
};

// Rendered per request, never cached. Everything on this page comes from the
// environment, and .next/cache is a volume that outlives the container -- so with any
// caching at all, correcting an address in .env and restarting leaves the old text
// being served, which is precisely what an Impressum must not do. The page is
// essentially untrafficked, so a render per visit costs nothing worth having.
export const dynamic = "force-dynamic";


/**
 * Impressum (§5 DDG) and privacy notice.
 *
 * The contact details come from IMPRESSUM_* in the environment, not from this file:
 * a published image must not carry one operator's address, and a wrong Impressum
 * needs to be fixable without a rebuild.
 *
 * The privacy section stays in source, because it describes what this codebase
 * actually does rather than who runs it. Keep it in step if the processing changes.
 */
export default function LegalPage() {
  const data = impressum();
  const missing = missingRequired(data);

  return (
    <div className="prose py-8">
      <h1 className="font-display text-3xl">Impressum</h1>

      {missing.length > 0 ? (
        <p className="border border-rule bg-raised p-4 font-mono text-sm not-prose">
          Diese Seite ist noch nicht vollständig konfiguriert. Fehlende Angaben:{" "}
          {missing.join(", ")}.
        </p>
      ) : (
        <address className="not-prose whitespace-pre-line not-italic">
          {[
            data.name,
            data.street,
            data.city,
            data.country,
            "",
            `E-Mail: ${data.email}`,
            data.phone && `Telefon: ${data.phone}`,
            data.vatId && `USt-IdNr.: ${data.vatId}`,
            data.editorialResponsible &&
              `Verantwortlich i.S.d. §18 Abs. 2 MStV: ${data.editorialResponsible}`,
          ]
            .filter(Boolean)
            .join("\n")}
        </address>
      )}

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
        bei einer Aufsichtsbehörde
      </p>
    </div>
  );
}
