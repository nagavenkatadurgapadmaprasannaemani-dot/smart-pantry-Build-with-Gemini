import numpy as np
import scipy.io.wavfile as wav

def generate_lofi_track(output_path="/config/Desktop/Session1/smart-pantry/lofi_track.wav", duration=35.0):
    sr = 44100
    num_samples = int(sr * duration)
    t = np.linspace(0, duration, num_samples, endpoint=False)

    bpm = 90
    beat_sec = 60.0 / bpm
    bar_sec = beat_sec * 4

    # Warm lo-fi Seventh Chords (Hz)
    chords = [
        [261.63, 329.63, 392.00, 493.88], # Cmaj7
        [220.00, 261.63, 329.63, 392.00], # Am7
        [293.66, 349.23, 440.00, 523.25], # Dm7
        [196.00, 246.94, 293.66, 349.23], # G7
    ]

    audio = np.zeros(num_samples)

    # 1. Warm Synth Chords with soft envelope and LFO
    for i in range(num_samples):
        bar_idx = int(t[i] / (bar_sec * 2)) % len(chords)
        current_chord = chords[bar_idx]
        
        bar_time = (t[i] % bar_sec) / bar_sec
        env = np.exp(-bar_time * 1.5) * 0.18
        lfo = 1.0 + 0.08 * np.sin(2 * np.pi * 0.5 * t[i])
        
        val = 0
        for freq in current_chord:
            val += np.sin(2 * np.pi * freq * t[i]) * 0.25
            val += np.sin(2 * np.pi * (freq * 0.5) * t[i]) * 0.15 # Warm sub-bass
        audio[i] += val * env * lfo

    # 2. Upbeat Lo-Fi Drum Beat (Kick, Snare, Hi-hat)
    num_steps = int(duration / (beat_sec / 2))
    for beat_i in range(num_steps):
        beat_time = beat_i * (beat_sec / 2)
        sample_idx = int(beat_time * sr)
        if sample_idx >= num_samples:
            break
        
        step = beat_i % 8
        
        # Punchy Kick on 0 and 5
        if step in [0, 5]:
            k_len = int(0.12 * sr)
            k_t = np.linspace(0, 0.12, k_len, endpoint=False)
            freq_env = 140 * np.exp(-k_t * 35) + 45
            kick = np.sin(2 * np.pi * freq_env * k_t) * np.exp(-k_t * 18) * 0.45
            end = min(sample_idx + k_len, num_samples)
            audio[sample_idx:end] += kick[:end-sample_idx]
            
        # Crisp Snare on 2 and 6
        if step in [2, 6]:
            s_len = int(0.15 * sr)
            s_t = np.linspace(0, 0.15, s_len, endpoint=False)
            noise = (np.random.rand(s_len) * 2 - 1) * np.exp(-s_t * 28) * 0.28
            tone = np.sin(2 * np.pi * 180 * s_t) * np.exp(-s_t * 35) * 0.22
            snare = noise + tone
            end = min(sample_idx + s_len, num_samples)
            audio[sample_idx:end] += snare[:end-sample_idx]
            
        # Crisp Hi-hat on every 8th note
        h_len = int(0.04 * sr)
        h_t = np.linspace(0, 0.04, h_len, endpoint=False)
        hihat = (np.random.rand(h_len) * 2 - 1) * np.exp(-h_t * 70) * 0.09
        end = min(sample_idx + h_len, num_samples)
        audio[sample_idx:end] += hihat[:end-sample_idx]

    # Normalize audio
    audio = np.clip(audio, -1.0, 1.0)
    audio_int16 = (audio * 32767).astype(np.int16)
    stereo_audio = np.column_stack((audio_int16, audio_int16))

    wav.write(output_path, sr, stereo_audio)
    print(f"Generated upbeat lo-fi track: {output_path}")

if __name__ == "__main__":
    generate_lofi_track()
