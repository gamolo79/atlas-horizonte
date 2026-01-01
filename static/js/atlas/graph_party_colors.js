(function (global) {
  const PARTY_COLORS = {
    "Partido Acción Nacional": { fill: "#0057B8", stroke: "#93C5FD" },
    "PRI": { fill: "#D50000", stroke: "#FCA5A5" },
    "Movimiento Ciudadano": { fill: "#FF6A00", stroke: "#FED7AA" },
    "Partido Verde Ecologista de México": { fill: "#1B8F2E", stroke: "#BBF7D0" },
    "Partido del Trabajo": { fill: "#F2C300", stroke: "#B91C1C" },
    "Movimiento de Regeneración Nacional": { fill: "#7A1F3D", stroke: "#FECACA" }
  };

  const PARTY_ALIASES = new Map([
    ["PAN", "Partido Acción Nacional"],
    ["PARTIDO ACCION NACIONAL", "Partido Acción Nacional"],
    ["PARTIDO ACCIÓN NACIONAL", "Partido Acción Nacional"],

    ["PRI", "PRI"],
    ["PARTIDO REVOLUCIONARIO INSTITUCIONAL", "PRI"],

    ["MC", "Movimiento Ciudadano"],
    ["MOVIMIENTO CIUDADANO", "Movimiento Ciudadano"],

    ["PVEM", "Partido Verde Ecologista de México"],
    ["PARTIDO VERDE", "Partido Verde Ecologista de México"],
    ["PARTIDO VERDE ECOLOGISTA DE MEXICO", "Partido Verde Ecologista de México"],
    ["PARTIDO VERDE ECOLOGISTA DE MÉXICO", "Partido Verde Ecologista de México"],

    ["PT", "Partido del Trabajo"],
    ["PARTIDO DEL TRABAJO", "Partido del Trabajo"],

    ["MORENA", "Movimiento de Regeneración Nacional"],
    ["MOVIMIENTO DE REGENERACION NACIONAL", "Movimiento de Regeneración Nacional"],
    ["MOVIMIENTO DE REGENERACIÓN NACIONAL", "Movimiento de Regeneración Nacional"]
  ]);

  function normalizePartyName(raw) {
    if (!raw) return null;
    const s = String(raw).trim();
    if (!s) return null;

    const upper = s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toUpperCase();
    if (PARTY_ALIASES.has(upper)) return PARTY_ALIASES.get(upper);

    if (PARTY_COLORS[s]) return s;

    if (upper.includes("ACCION NACIONAL")) return "Partido Acción Nacional";
    if (upper.includes("REVOLUCIONARIO INSTITUCIONAL")) return "PRI";
    if (upper.includes("MOVIMIENTO CIUDADANO")) return "Movimiento Ciudadano";
    if (upper.includes("VERDE")) return "Partido Verde Ecologista de México";
    if (upper.includes("DEL TRABAJO")) return "Partido del Trabajo";
    if (upper.includes("REGENERACION NACIONAL") || upper.includes("MORENA")) {
      return "Movimiento de Regeneración Nacional";
    }

    return s;
  }

  function hashStringToInt(str) {
    let h = 0;
    for (let i = 0; i < str.length; i++) {
      h = (h * 31 + str.charCodeAt(i)) >>> 0;
    }
    return h;
  }

  function hslToHex(h, s, l) {
    s /= 100;
    l /= 100;
    const k = n => (n + h / 30) % 12;
    const a = s * Math.min(l, 1 - l);
    const f = n => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
    const toHex = x => Math.round(255 * x).toString(16).padStart(2, "0");
    return `#${toHex(f(0))}${toHex(f(8))}${toHex(f(4))}`;
  }

  function randomColorFromName(name) {
    const seed = hashStringToInt(String(name || "desconocido"));
    const hue = seed % 360;
    return hslToHex(hue, 65, 45);
  }

  function stablePartyColor(partyName, fallbackKey) {
    if (!partyName) {
      const fill = randomColorFromName(fallbackKey || "sin-partido");
      return { fill, stroke: "#111827" };
    }
    const canonical = normalizePartyName(partyName);
    if (canonical && PARTY_COLORS[canonical]) return PARTY_COLORS[canonical];

    const fill = randomColorFromName(canonical || fallbackKey || "otro");
    return { fill, stroke: "#111827" };
  }

  function partyFillColor(partyName, fallbackKey) {
    return stablePartyColor(partyName, fallbackKey).fill;
  }

  global.AtlasPartyColors = {
    PARTY_COLORS,
    normalizePartyName,
    stablePartyColor,
    partyFillColor
  };
})(window);
