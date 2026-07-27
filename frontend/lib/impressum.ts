/**
 * Anbieterkennzeichnung, from the environment rather than the source.
 *
 * A published image must not carry one operator's postal address, and an Impressum
 * must be correctable without a rebuild — §5 DDG requires it to be accurate, and a
 * redeploy is a poor gate on fixing a wrong address. Read at render time; `/legal`
 * carries a `revalidate` so a changed value reaches the page on its own.
 */

export type Impressum = {
  name: string;
  street: string;
  city: string;
  country: string;
  email: string;
  phone: string;
  vatId: string;
  /** §18 Abs. 2 MStV — only required for journalistic-editorial content. */
  editorialResponsible: string;
  /** Supervisory authority for the DSGVO rights section. */
  supervisoryAuthority: string;
};

const FIELDS: Record<keyof Impressum, string> = {
  name: "IMPRESSUM_NAME",
  street: "IMPRESSUM_STREET",
  city: "IMPRESSUM_CITY",
  country: "IMPRESSUM_COUNTRY",
  email: "IMPRESSUM_EMAIL",
  phone: "IMPRESSUM_PHONE",
  vatId: "IMPRESSUM_VAT_ID",
  editorialResponsible: "IMPRESSUM_EDITORIAL_RESPONSIBLE",
  supervisoryAuthority: "IMPRESSUM_SUPERVISORY_AUTHORITY",
};

export function impressum(): Impressum {
  return Object.fromEntries(
    Object.entries(FIELDS).map(([key, variable]) => [key, (process.env[variable] ?? "").trim()]),
  ) as unknown as Impressum;
}

/**
 * The subset §5 DDG actually compels: who you are, where you can be reached in
 * writing, and a way to contact you quickly. Everything else on the page is
 * conditional, so it renders only when supplied.
 *
 * Returned rather than thrown so a missing value produces a visible warning on the
 * page instead of a 500 that takes the whole site down.
 */
export function missingRequired(data: Impressum): string[] {
  return (["name", "street", "city", "email"] as const)
    .filter((key) => !data[key])
    .map((key) => FIELDS[key]);
}
