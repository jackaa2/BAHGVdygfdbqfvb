"""Keep captions on the streamer only: drop game dialogue, donation voices and background chatter.

1. confidence: drop bits Whisper isn't sure are speech
2. loudness:   the streamer's mic is the loudest voice; drop much quieter speech (game audio, TTS under music)
3. voice:      voice fingerprints (ECAPA) -> keep the voice that talks the most (the streamer)
Every step falls back safely: if a step would remove most of the speech, it is skipped.
"""
import numpy as np

SR = 16000
QUIET_DB = 10          # drop speech this many dB quieter than the main voice
VOICE_MIN_SIM = 0.30   # cosine similarity to the main voice to count as "same person"
MIN_EMB_SECONDS = 0.8  # shorter bits can't be fingerprinted reliably -> judged by loudness only

_encoder = None


def _db(x):
    if x.size == 0:
        return -120.0
    return 20 * np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-9)


def _seg_audio(audio, seg):
    parts = [audio[int(w["start"] * SR):int(w["end"] * SR)] for w in seg["words"]] or \
            [audio[int(seg["start"] * SR):int(seg["end"] * SR)]]
    return np.concatenate(parts) if parts else np.zeros(0, np.float32)


def _speech_time(segs):
    return sum(max(s["end"] - s["start"], 0) for s in segs)


def _embed(chunks):
    global _encoder
    import torch
    from speechbrain.inference.speaker import EncoderClassifier
    if _encoder is None:
        import os
        _encoder = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=os.path.expanduser("~/.cache/huggingface/speechbrain-ecapa"),
            run_opts={"device": "cpu"})
    out = []
    with torch.no_grad():
        for c in chunks:
            e = _encoder.encode_batch(torch.from_numpy(c.astype(np.float32))[None]).squeeze().numpy()
            out.append(e / (np.linalg.norm(e) + 1e-9))
    return out


def keep_streamer(audio, segs, log=print):
    """segs: [{start,end,text,words:[{word,start,end}],no_speech_prob,avg_logprob}] -> filtered segs"""
    if not segs:
        return segs
    total = _speech_time(segs)

    # 1. confidence
    s1 = [s for s in segs if not (s["no_speech_prob"] > 0.6 and s["avg_logprob"] < -0.7)
          and s["avg_logprob"] > -1.3]
    if _speech_time(s1) < 0.3 * total:
        s1 = segs
    # 2. loudness
    lv = [_db(_seg_audio(audio, s)) for s in s1]
    weights = [max(s["end"] - s["start"], 0.1) for s in s1]
    order = np.argsort(lv)
    cum, ref = 0.0, max(lv)
    for i in order[::-1]:            # level that covers the loudest ~40% of speech time
        cum += weights[i]
        if cum >= 0.4 * sum(weights):
            ref = lv[i]
            break
    s2 = [s for s, l in zip(s1, lv) if l >= ref - QUIET_DB]
    if _speech_time(s2) < 0.4 * _speech_time(s1):
        s2 = s1
    dropped = [s["text"] for s in s1 if s not in s2]
    if dropped:
        log(f"   quiet voices skipped: {dropped[:4]}")

    # 3. voice fingerprint: keep the person who talks the most
    try:
        long_ = [s for s in s2 if s["end"] - s["start"] >= MIN_EMB_SECONDS]
        if len(long_) < 3:
            log("   voice check: too little speech to compare voices, kept all")
        if len(long_) >= 3:
            embs = _embed([_seg_audio(audio, s) for s in long_])
            w = np.array([s["end"] - s["start"] for s in long_])
            E = np.stack(embs)
            centroid = (E * w[:, None]).sum(0)
            for _ in range(4):  # pull the centre toward the majority voice
                centroid /= np.linalg.norm(centroid) + 1e-9
                sims = E @ centroid
                keep = sims >= np.quantile(sims, 0.35)
                centroid = (E[keep] * w[keep, None]).sum(0)
            centroid /= np.linalg.norm(centroid) + 1e-9
            sims = E @ centroid
            other = {id(s) for s, sim in zip(long_, sims) if sim < VOICE_MIN_SIM}
            s3 = [s for s in s2 if id(s) not in other]
            if other and _speech_time(s3) >= 0.4 * _speech_time(s2):
                log(f"   other voices skipped: {[s['text'] for s in s2 if id(s) in other][:4]}")
                s2 = s3
    except Exception as e:  # never lose captions because of this step
        log(f"   voice check skipped: {e}")
    log(f"   speaker filter: kept {len(s2)}/{len(segs)} speech bits")
    return s2
