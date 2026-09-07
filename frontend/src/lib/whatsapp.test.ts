/**
 * Numerele așa cum sunt scrise în fișele de clienți, nu cum ne-ar plăcea.
 *
 * Cazurile de mai jos sunt formele reale în care ajunge un număr într-un CRM
 * românesc: dictat la telefon, copiat dintr-un email, lipit dintr-o factură.
 * Butonul de WhatsApp trebuie să meargă pentru toate — sau, dacă nu poate, să
 * nu existe. Un link care se deschide într-o eroare este mai rău decât unul
 * absent: omul apasă o dată, se lovește, și nu mai apasă niciodată.
 */
import { describe, expect, it } from "vitest";
import { whatsappHref, whatsappNumber } from "@/lib/whatsapp";

describe("whatsappNumber", () => {
  it("acceptă forma locală, cu tot cu spații", () => {
    // Forma în care îl scrie oricine în România. Înainte, exact ea producea un
    // link stricat: `wa.me/0722123456`, cu zero în față și fără prefix de țară.
    expect(whatsappNumber("0722 123 456")).toBe("40722123456");
    expect(whatsappNumber("0722123456")).toBe("40722123456");
    expect(whatsappNumber("0722.123.456")).toBe("40722123456");
    expect(whatsappNumber("0722-123-456")).toBe("40722123456");
  });

  it("acceptă formele internaționale, oricum ar fi scrise", () => {
    expect(whatsappNumber("+40722123456")).toBe("40722123456");
    expect(whatsappNumber("+40 722 123 456")).toBe("40722123456");
    expect(whatsappNumber("0040722123456")).toBe("40722123456");
    expect(whatsappNumber("40722123456")).toBe("40722123456");
  });

  it("acceptă numărul dictat fără nimic în față", () => {
    expect(whatsappNumber("722123456")).toBe("40722123456");
  });

  it("nu presupune România pentru un număr care are deja altă țară", () => {
    // Un client cu administrator în Italia. Presupunerea ar fi trimis mesajul
    // unui necunoscut cu același număr în România.
    expect(whatsappNumber("+39 333 1234567")).toBe("393331234567");
    expect(whatsappNumber("0039 333 1234567")).toBe("393331234567");
  });

  it("refuză ce nu poate fi un număr de telefon", () => {
    // Interiorul de firmă, notat în graba unui apel. Un link către `wa.me/123`
    // s-ar deschide într-o eroare.
    expect(whatsappNumber("123")).toBeNull();
    expect(whatsappNumber("int. 204")).toBeNull();
    expect(whatsappNumber("07221234567890123456")).toBeNull();
    expect(whatsappNumber("")).toBeNull();
    expect(whatsappNumber(null)).toBeNull();
    expect(whatsappNumber(undefined)).toBeNull();
  });
});

describe("whatsappHref", () => {
  it("deschide conversația, fără text când nu avem ce scrie", () => {
    expect(whatsappHref("0722 123 456")).toBe("https://wa.me/40722123456");
  });

  it("duce mesajul cu diacritice și rânduri noi întreg", () => {
    // Solicitarea de documente are liste, un link și diacritice. Codificată
    // prost, clientul ar primi un text rupt exact la primul „ș".
    const href = whatsappHref("0722 123 456", "Bună ziua,\n• Facturi de achiziție");

    expect(href).toBe(
      "https://wa.me/40722123456?text=" +
        encodeURIComponent("Bună ziua,\n• Facturi de achiziție"),
    );
    expect(href).not.toContain(" ");
  });

  it("nu produce niciun link pentru un număr imposibil", () => {
    expect(whatsappHref("int. 204", "orice")).toBeNull();
  });
});
