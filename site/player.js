// Lecteur unique de la page : il pilote le lecteur intégré de la plateforme (une iframe isolée) par
// messages, comme le font les bibliothèques officielles de Spotify, SoundCloud et YouTube, mais sans
// charger leurs scripts dans la page. Chaque plateforme a son dialecte ; `read` le traduit en un état
// commun : { platform, src, ready, playing, position, duration, ended, failed, volumeSupported },
// en secondes. Le volume (0 à 100) vaut pour toutes les sources : il est réappliqué à chacune.

export const ORIGINS = {
  soundcloud: "https://w.soundcloud.com",
  spotify: "https://open.spotify.com",
  youtube: "https://www.youtube-nocookie.com",
};

/** Sans réponse du lecteur passé ce délai, la page le montre tel quel, avec ses propres commandes. */
const READY_TIMEOUT_MS = 10_000;
const HELLO_EVERY_MS = 250;

/** Lecteur YouTube : -1 pas démarré, 0 fini, 1 en lecture, 2 en pause, 3 chargement, 5 prêt. */
function youtubeState(code) {
  if (code === 1) return { playing: true, ended: false };
  if (code === 0) return { playing: false, ended: true };
  return code === 3 ? {} : { playing: false };
}

const youtubeCommand = (func, args = []) => ({ event: "command", func, args, id: 1, channel: "widget" });

export const DIALECTS = {
  // Widget API de SoundCloud (api.js) : messages JSON { method, value }.
  soundcloud: {
    encode: JSON.stringify,
    onReady: [
      ...["play", "pause", "finish", "playProgress"].map((value) => ({ method: "addEventListener", value })),
      { method: "getDuration" },
      { method: "isPaused" }, // le lecteur a pu démarrer seul avant qu'on l'écoute
    ],
    read(message, state) {
      const { method, value } = message ?? {};
      if (method === "ready") return { ready: true };
      if (method === "play") return { playing: true, ended: false };
      if (method === "pause") return { playing: false };
      if (method === "finish") return { playing: false, ended: true };
      if (method === "isPaused") return { playing: !value };
      if (method === "getDuration" && value > 0) return { duration: value / 1000 };
      if (method === "playProgress" && value) {
        const position = value.currentPosition / 1000;
        // Dans une playlist, chaque son a sa durée : la position relative la donne.
        const duration = value.relativePosition > 0 ? position / value.relativePosition : state.duration;
        return { position, duration };
      }
      return null;
    },
    play: () => [{ method: "play" }],
    pause: () => [{ method: "pause" }],
    seek: (seconds) => [{ method: "seekTo", value: Math.round(seconds * 1000) }],
    volume: (level) => [{ method: "setVolume", value: level }],
  },
  // iFrame API de Spotify : objets { command } envoyés, { type, payload } reçus (millisecondes).
  spotify: {
    encode: (message) => message,
    onReady: [{ command: "resume" }],
    read(message, state) {
      if (message?.type === "ready") return { ready: true };
      if (message?.type !== "playback_update" || !message.payload) return null;
      const { isPaused, position, duration } = message.payload;
      const patch = { playing: !isPaused, position: position / 1000, duration: duration / 1000 };
      // Fin d'un titre : la position atteint la durée (sans pause), ou la lecture s'arrête au bout.
      const atEnd = duration > 0 && position >= duration;
      const stoppedAtEnd = isPaused && state.playing && state.duration && state.position >= state.duration - 1.5;
      if (atEnd || stoppedAtEnd) patch.ended = true;
      return patch;
    },
    play: () => [{ command: "resume" }],
    pause: () => [{ command: "pause" }],
    seek: (seconds) => [{ command: "seek", timestamp: seconds }],
    // Pas de volume : l'iFrame API de Spotify n'en a pas, celui de l'appareil s'applique.
  },
  // IFrame API de YouTube : le lecteur ne parle qu'après un message « listening ».
  youtube: {
    encode: JSON.stringify,
    hello: { event: "listening", id: 1, channel: "widget" },
    onReady: [],
    read(message) {
      if (!message?.event) return null;
      if (message.event === "onReady") return { ready: true };
      if (message.event === "onStateChange") return { ready: true, ...youtubeState(message.info) };
      if (message.event !== "infoDelivery" && message.event !== "initialDelivery") return null;
      const info = message.info ?? {};
      const patch = { ready: true };
      if (typeof info.currentTime === "number") patch.position = info.currentTime;
      if (info.duration > 0) patch.duration = info.duration;
      if (typeof info.playerState === "number") Object.assign(patch, youtubeState(info.playerState));
      return patch;
    },
    play: () => [youtubeCommand("playVideo")],
    pause: () => [youtubeCommand("pauseVideo")],
    seek: (seconds) => [youtubeCommand("seekTo", [seconds, true])],
    volume: (level) => [youtubeCommand(level > 0 ? "unMute" : "mute"), youtubeCommand("setVolume", [level])],
  },
};

function parse(data) {
  if (typeof data !== "string") return data;
  try {
    return JSON.parse(data);
  } catch {
    return null;
  }
}

/** Lecteur unique : `host` reçoit l'iframe de la source jouée, `onChange` chaque nouvel état. */
export function createPlayer(host, onChange) {
  let current = null;
  let volume = 100;
  const applyVolume = (entry) => {
    if (entry.dialect.volume && entry.state.ready) for (const message of entry.dialect.volume(volume)) send(entry, message);
  };

  const send = (entry, message) =>
    entry.iframe.contentWindow?.postMessage(entry.dialect.encode(message), ORIGINS[entry.platform]);
  const notify = (entry) => onChange({ ...entry.state });

  addEventListener("message", (event) => {
    const entry = current;
    // Seul le lecteur en cours, depuis son origine, est écouté ; ses messages ne sont que des données.
    if (!entry || event.source !== entry.iframe.contentWindow || event.origin !== ORIGINS[entry.platform]) return;
    const patch = entry.dialect.read(parse(event.data), entry.state);
    if (!patch) return;
    // Une fin n'est signalée qu'une fois (Spotify la répète) ; une relance la réarme.
    if (patch.ended && entry.finished) delete patch.ended;
    else if (patch.ended) entry.finished = true;
    const wasReady = entry.state.ready;
    Object.assign(entry.state, patch);
    if (entry.state.ready && !wasReady) {
      clearTimeout(entry.timeout);
      clearInterval(entry.hello);
      for (const message of entry.dialect.onReady) send(entry, message);
      applyVolume(entry); // chaque nouvelle source garde le volume choisi
    }
    notify(entry);
    entry.state.ended = false;
  });

  const stop = () => {
    if (!current) return;
    clearTimeout(current.timeout);
    clearInterval(current.hello);
    current = null;
    host.replaceChildren();
  };

  return {
    /** Charge une source { platform, src, title } ; elle démarre seule une fois prête. */
    load({ platform, src, title }) {
      stop();
      const args = { platform, src, title };
      const iframe = Object.assign(document.createElement("iframe"), {
        src,
        title,
        allow: "autoplay; encrypted-media; fullscreen; picture-in-picture",
        referrerPolicy: "strict-origin-when-cross-origin", // YouTube refuse les intégrations sans origine
      });
      const dialect = DIALECTS[platform];
      const entry = {
        args,
        platform,
        iframe,
        dialect,
        state: {
          platform,
          src,
          ready: false,
          playing: false,
          position: 0,
          duration: 0,
          ended: false,
          failed: false,
          volumeSupported: Boolean(dialect.volume),
        },
      };
      if (dialect.hello) {
        iframe.addEventListener("load", () => {
          entry.hello = setInterval(() => send(entry, dialect.hello), HELLO_EVERY_MS);
        });
      }
      entry.timeout = setTimeout(() => {
        entry.state.failed = true;
        clearInterval(entry.hello);
        notify(entry);
      }, READY_TIMEOUT_MS);
      current = entry;
      host.replaceChildren(iframe);
      notify(entry);
    },
    play() {
      if (!current) return;
      current.finished = false;
      for (const message of current.dialect.play()) send(current, message);
    },
    pause() {
      if (current) for (const message of current.dialect.pause()) send(current, message);
    },
    toggle() {
      if (current?.state.playing) this.pause();
      else this.play();
    },
    seek(seconds) {
      if (!current) return;
      current.finished = false;
      for (const message of current.dialect.seek(seconds)) send(current, message);
      current.state.position = seconds; // sans attendre la confirmation du lecteur
      notify(current);
    },
    /** Volume de 0 à 100, pour la source en cours et les suivantes. */
    setVolume(level) {
      volume = level;
      if (current) applyVolume(current);
    },
    /** Recharge la source en cours (après une connexion à Spotify, par exemple). */
    reload() {
      if (current) this.load(current.args);
    },
    stop,
    get state() {
      return current ? { ...current.state } : null;
    },
  };
}
