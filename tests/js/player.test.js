import assert from "node:assert/strict";
import test from "node:test";

import { DIALECTS } from "../../site/player.js";

// Messages réels des lecteurs, relevés le 26/10/2026.
const idle = { ready: true, playing: false, position: 0, duration: 0 };

test("SoundCloud : prêt, lecture, position et durée d'un son de playlist", () => {
  const { read, seek } = DIALECTS.soundcloud;
  assert.deepEqual(read({ widgetId: "w", method: "ready", value: null }, idle), { ready: true });
  assert.deepEqual(read({ method: "getDuration", value: 213890 }, idle), { duration: 213.89 });
  assert.deepEqual(read({ method: "isPaused", value: false }, idle), { playing: true });
  const progress = read(
    { method: "playProgress", value: { currentPosition: 120000.001, relativePosition: 0.5610360512412923 } },
    idle,
  );
  assert.equal(Math.round(progress.position), 120);
  assert.equal(Math.round(progress.duration), 214);
  assert.deepEqual(read({ method: "finish", value: null }, idle), { playing: false, ended: true });
  assert.deepEqual(seek(61.5), [{ method: "seekTo", value: 61500 }]);
  assert.equal(read({ method: "inconnu" }, idle), null);
});

test("Spotify : avancement, et fin détectée quand la lecture s'arrête au bout", () => {
  const { read, seek } = DIALECTS.spotify;
  const update = (isPaused, position) => ({
    type: "playback_update",
    payload: { isPaused, isBuffering: false, duration: 21867, position, playingURI: "spotify:track:x" },
  });
  assert.deepEqual(read({ type: "ready" }, idle), { ready: true });
  assert.deepEqual(read(update(false, 9542), idle), { playing: true, position: 9.542, duration: 21.867 });
  assert.equal(read(update(false, 21867), idle).ended, true); // fin réelle : position = durée
  const nearEnd = { ...idle, playing: true, position: 21.2, duration: 21.867 };
  assert.equal(read(update(true, 0), nearEnd).ended, true);
  assert.equal(read(update(true, 5000), { ...nearEnd, position: 5 }).ended, undefined); // simple pause
  assert.deepEqual(seek(8), [{ command: "seek", timestamp: 8 }]);
});

test("YouTube : poignée de main, informations et états du lecteur", () => {
  const { read, hello, seek } = DIALECTS.youtube;
  assert.deepEqual(hello, { event: "listening", id: 1, channel: "widget" });
  assert.deepEqual(read({ event: "onReady" }, idle), { ready: true });
  assert.deepEqual(read({ event: "infoDelivery", info: { currentTime: 42.5, duration: 200, playerState: 1 } }, idle), {
    ready: true,
    position: 42.5,
    duration: 200,
    playing: true,
    ended: false,
  });
  assert.deepEqual(read({ event: "onStateChange", info: 0 }, idle), { ready: true, playing: false, ended: true });
  assert.deepEqual(read({ event: "onStateChange", info: 2 }, idle), { ready: true, playing: false });
  assert.deepEqual(seek(30), [{ event: "command", func: "seekTo", args: [30, true], id: 1, channel: "widget" }]);
  assert.equal(read("pas un message", idle), null);
});

test("volume : SoundCloud et YouTube le règlent, Spotify non (volume de l'appareil)", () => {
  assert.deepEqual(DIALECTS.soundcloud.volume(25), [{ method: "setVolume", value: 25 }]);
  assert.deepEqual(DIALECTS.youtube.volume(40), [
    { event: "command", func: "unMute", args: [], id: 1, channel: "widget" },
    { event: "command", func: "setVolume", args: [40], id: 1, channel: "widget" },
  ]);
  assert.equal(DIALECTS.youtube.volume(0)[0].func, "mute");
  assert.equal(DIALECTS.spotify.volume, undefined);
});
