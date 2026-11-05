// Narrated motion-graphics starter for the media-tooling raea pilot.
//
// Reads ./scenes.json and the words that `media-raea-timing` writes, so every cue follows the narration:
//   media-raea-timing --audio-meta <slot>/audio_meta.json --root . --lead 0.5 --scene-ids hook,point,close
// Full film:   raea render edit.tsx --lite --words words.json --at 15,90 -o stills/
// One scene:   raea render edit.tsx --lite --composition point --words words-point.json --at 0,60 -o stills/
// Replace the palette, faces and scene bodies; keep the timing plumbing.
import { AbsoluteFill, Animate, Audio, Composition, Sequence, fade, registerRoot, rise, staticFile, useWords, type TimelineWord } from "raea";
import timing from "./scenes.json";

type SceneTiming = { id: string; start: number; dur: number; from: number; frames: number; cues: Record<string, number> };
type SceneProps = { scene: SceneTiming };
const FPS = timing.fps;
const f = (s: number) => Math.round(s * FPS);

// ---- look: palette, faces, type (from the slot's design spec; never invent a palette for a branded piece) ----
const C = { bg: "#F2EFE9", ink: "#161616", muted: "#5C5C5C", accent: "#2F5BEA", line: "#C9C3B8" };
const DISPLAY = "Helvetica Neue"; // a face this Mac has, or one declared in FACES
const TEXT = "Helvetica Neue";
// Vendored faces render offline and identically: put the files in media/fonts/ and list them here.
const FACES: { family: string; file: string; weight: number; style?: "normal" | "italic" }[] = [
  // { family: "Inter", file: "Inter-500.ttf", weight: 500 },
];
const FACE_CSS = FACES.map((x) => `@font-face { font-family: "${x.family}"; font-weight: ${x.weight}; font-style: ${x.style ?? "normal"}; src: url("${staticFile(`fonts/${x.file}`)}"); }`).join("\n");
const TYPE = {
  kicker: { fontFamily: TEXT, fontWeight: 600, fontSize: 28, letterSpacing: 4, color: C.accent },
  title: { fontFamily: DISPLAY, fontWeight: 700, fontSize: 96, lineHeight: 1.05, color: C.ink, fontVariantNumeric: "lining-nums tabular-nums" },
  body: { fontFamily: TEXT, fontWeight: 400, fontSize: 40, lineHeight: 1.4, color: C.muted },
} as const;

// ---- timing helpers ----
/** scene-local frame of the nth time a word is said in this scene (outer punctuation and case ignored) */
function useWord(scene: SceneTiming) {
  const words = useWords().filter((w: TimelineWord) => w.from >= 0 && w.from < scene.frames);
  const norm = (s: string) => s.toLowerCase().replace(/^[^\p{L}\p{N}$]+|[^\p{L}\p{N}%]+$/gu, "");
  return (word: string, nth = 1) => {
    const hit = words.filter((w) => norm(w.text) === norm(word))[nth - 1];
    if (!hit) throw new Error(`${scene.id}: word not found: ${word} #${nth}`);
    return hit.from;
  };
}
/** scene-local frame of a {@cue} from media-tts-frames */
const cue = (scene: SceneTiming, name: string) => {
  if (!(name in scene.cues)) throw new Error(`${scene.id}: no cue {@${name}}`);
  return f(scene.cues[name]);
};
/** a free track on Sequence frames: `animate` tracks ignore `at`, so key them where they happen */
const grow = (at: number, frames: number, to: number, from = 0) => ({ [at]: from, [at + frames]: to });

// ---- parts ----
const Kicker = ({ text, at, top }: { text: string; at: number; top: number }) => (
  <Animate enter={fade({ frames: 12 })} at={at} style={{ ...TYPE.kicker, position: "absolute", left: 96, top }}>{text.toUpperCase()}</Animate>
);

/** the default scene: a kicker, a title on the first word, a rule, one supporting line. Replace per scene. */
function TitleScene({ scene }: SceneProps) {
  const first = useWords().find((w: TimelineWord) => w.from >= 0 && w.from < scene.frames);
  const at = first ? first.from : 0;
  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      <Kicker text={scene.id} at={6} top={420} />
      <Animate enter={rise({ distance: 24, frames: 14, fade: 12 })} at={at} style={{ ...TYPE.title, position: "absolute", left: 92, top: 470, width: 880 }}>
        {first ? first.text : scene.id}
      </Animate>
      <Animate animate={{ width: grow(at + 8, 18, 240) }} style={{ position: "absolute", left: 96, top: 600, width: 0, height: 3, backgroundColor: C.ink }} />
      <Animate enter={rise({ distance: 16, frames: 12, fade: 12 })} at={at + 14} style={{ ...TYPE.body, position: "absolute", left: 96, top: 630, width: 860 }}>
        {scene.frames} frames · {Object.keys(scene.cues).length} cues
      </Animate>
    </AbsoluteFill>
  );
}

/** scene id -> body; scenes not listed use TitleScene */
const BODIES: Record<string, (p: SceneProps) => JSX.Element> = {};

// ---- captions: groups of up to 3 words, broken at punctuation and at pauses over 8 frames ----
function groups(words: TimelineWord[]): TimelineWord[][] {
  const out: TimelineWord[][] = [];
  for (const w of words) {
    const g = out[out.length - 1];
    const last = g?.[g.length - 1];
    if (!g || g.length >= 3 || /[.,;:?!]$/.test(last.text) || w.from - last.to > 8) out.push([w]);
    else g.push(w);
  }
  return out;
}

function Captions() {
  const gs = groups(useWords());
  return (
    <>
      {gs.map((g, i) => {
        const from = g[0].from;
        const until = i + 1 < gs.length ? Math.min(gs[i + 1][0].from, g[g.length - 1].to + 8) : g[g.length - 1].to + 8;
        return (
          <Sequence key={i} from={from} durationInFrames={Math.max(1, until - from)} name={`cap-${i}`}>
            <Animate enter={rise({ distance: 6, frames: 4, fade: 4 })} style={{ position: "absolute", left: 0, right: 0, top: 1380, display: "flex", flexDirection: "column", alignItems: "center" }}>
              <div style={{ maxWidth: 860, padding: "14px 30px 16px", backgroundColor: "rgba(242,239,233,0.94)", border: `1px solid ${C.line}`, fontFamily: TEXT, fontWeight: 600, fontSize: 60, lineHeight: 1.2, color: C.ink, textAlign: "center" }}>
                {g.map((w) => w.text).join(" ")}
              </div>
            </Animate>
          </Sequence>
        );
      })}
    </>
  );
}

function Scene({ scene }: SceneProps) {
  const Body = BODIES[scene.id] ?? TitleScene;
  return <Body scene={scene} />;
}

function Film() {
  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      <style>{FACE_CSS}</style>
      {timing.scenes.map((s: SceneTiming) => (
        <Sequence key={s.id} from={s.from} durationInFrames={s.frames} name={s.id}>
          <Scene scene={s} />
        </Sequence>
      ))}
      <Captions />
      {timing.voices.map((v, i) => (
        <Sequence key={`vo-${i}`} from={f(v.start)} layout="none" name={`voice-${v.scene}`}>
          <Audio src={staticFile(v.src)} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
}

/** one scene on its own clock, for fast stills and drafts (pair with --words words-<id>.json) */
function SceneOnly({ id }: { id: string }) {
  const s = timing.scenes.find((x: SceneTiming) => x.id === id)!;
  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      <style>{FACE_CSS}</style>
      <Scene scene={{ ...s, from: 0 }} />
    </AbsoluteFill>
  );
}

registerRoot(() => (
  <>
    <Composition id="film" component={Film} width={1080} height={1920} fps={FPS} durationInFrames={timing.frames} />
    {timing.scenes.map((s: SceneTiming) => (
      <Composition key={s.id} id={s.id} component={() => <SceneOnly id={s.id} />} width={1080} height={1920} fps={FPS} durationInFrames={s.frames} />
    ))}
  </>
));
