(function () {
window.fabroInitReviewVoice = function (root, scope) {
    'use strict';
    if (!root.querySelector('[data-review-voice], [data-review-voice-history]')) return;
    const recorders = new Map();
    const fallbackWave = Array.from({ length: 32 }, (_, i) => [18, 35, 65, 45, 80, 52, 30, 60][i % 8]);
    let activeAudio = null;
    const seconds = value => `${Math.floor(Math.max(0, value || 0) / 60)}:${String(Math.floor(Math.max(0, value || 0) % 60)).padStart(2, '0')}`;

    function waveform(canvas, levels, progress = 0, color = '#a78bfa', track = '#52525b') {
        const context = canvas.getContext('2d');
        const width = canvas.width, height = canvas.height, step = width / levels.length;
        context.clearRect(0, 0, width, height);
        function bars(fill) {
            context.fillStyle = fill;
            levels.forEach((level, i) => {
                const bar = Math.max(2, height * level / 100);
                context.fillRect(i * step + 1, (height - bar) / 2, Math.max(1, step - 3), bar);
            });
        }
        bars(track);
        context.save(); context.beginPath(); context.rect(0, 0, width * progress, height); context.clip(); bars(color); context.restore();
    }

    function paintBubble(audio) {
        const bubble = audio.closest('.review-voice-bubble');
        if (!bubble) return;
        const total = Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : Number(bubble.dataset.duration) / 1000;
        const elapsed = audio.currentTime || 0;
        const progress = Math.max(0, Math.min(1, total ? elapsed / total : 0));
        const seek = bubble.querySelector('input[type="range"]');
        seek.value = Math.round(progress * 1000);
        seek.setAttribute('aria-valuetext', `${seconds(elapsed)} / ${seconds(total)}`);
        bubble.querySelector('.voice-time').textContent = `${seconds(elapsed)} / ${seconds(total)}`;
        const button = bubble.querySelector('.voice-play');
        button.textContent = audio.paused ? '▶' : '❚❚';
        button.setAttribute('aria-label', audio.paused ? 'Play voice note' : 'Pause voice note');
        button.setAttribute('aria-pressed', String(!audio.paused));
        const css = getComputedStyle(bubble);
        waveform(bubble.querySelector('canvas'), JSON.parse(bubble.dataset.waveform), progress,
            css.getPropertyValue('--voice-accent').trim() || '#a78bfa', css.getPropertyValue('--voice-track').trim() || '#52525b');
    }

    function bubble(note, preview = false) {
        const root = document.createElement('div');
        root.className = 'review-voice-bubble';
        root.dataset.duration = note.duration_ms;
        root.dataset.waveform = JSON.stringify(note.waveform?.length ? note.waveform : fallbackWave);
        root.innerHTML = '<button type="button" class="voice-play" aria-label="Play voice note" aria-pressed="false">▶</button><div class="voice-message-body"><div class="voice-message-meta"></div><div class="voice-wave-seek"><canvas width="640" height="64" aria-hidden="true"></canvas><input type="range" min="0" max="1000" step="1" value="0" aria-label="Seek voice note"></div><output class="voice-time"></output></div><audio data-review-voice-audio preload="none"></audio>';
        root.querySelector('.voice-message-meta').textContent = preview ? 'Preview' : `${note.stage} · ${note.reviewer} · ${note.reviewed_at}`;
        const audio = root.querySelector('audio');
        const url = new URL(note.url, location.href);
        if (preview ? url.protocol !== 'blob:' : url.origin !== location.origin || !/^\/design-review-voice\/\d+\/$/.test(url.pathname)) return document.createDocumentFragment();
        audio.src = url.href;
        paintBubble(audio);
        return root;
    }

    function stopPlaybackWithin(root) {
        root.querySelectorAll('audio[data-review-voice-audio]').forEach(audio => {
            audio.pause(); audio.removeAttribute('src'); audio.load();
        });
    }

    function appendBubbles(root, notes) {
        notes.forEach(note => root.append(bubble(note)));
    }

    function releaseMicrophone(state) {
        clearInterval(state.timer);
        cancelAnimationFrame(state.animation);
        state.stream?.getTracks().forEach(track => track.stop());
        state.stream = null;
        state.context?.close().catch(() => {});
        state.context = null;
    }

    function reset(state) {
        state.generation++;
        if (state.recorder?.state === 'recording') state.recorder.stop();
        releaseMicrophone(state);
        state.mode = 'idle'; state.file = null;
        if (state.url) URL.revokeObjectURL(state.url);
        state.url = null;
        stopPlaybackWithin(state.root);
        state.root.querySelector('input[type="file"]').value = '';
        state.root.querySelector('[data-voice-recording]').hidden = true;
        state.root.querySelector('[data-voice-preview]').hidden = true;
        state.root.querySelector('[data-voice-preview-bubble]').replaceChildren();
        state.root.querySelector('[data-voice-error]').hidden = true;
        const button = state.root.querySelector('[data-voice-action="record"]');
        button.disabled = !state.supported; button.setAttribute('aria-label', 'Record voice note');
    }

    function showError(state, message) {
        const error = state.root.querySelector('[data-voice-error]');
        error.textContent = message; error.hidden = false;
    }

    function stop(state) {
        if (state.mode !== 'recording') return;
        state.mode = 'finishing';
        state.recorder.stop();
        releaseMicrophone(state);
    }

    async function start(state) {
        reset(state);
        for (const other of recorders.values()) if (other !== state && ['recording', 'pending'].includes(other.mode)) reset(other);
        activeAudio?.pause();
        const generation = state.generation;
        state.mode = 'pending';
        const button = state.root.querySelector('[data-voice-action="record"]');
        button.disabled = true;
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 }, video: false });
            if (generation !== state.generation || scope.signal.aborted) { stream.getTracks().forEach(track => track.stop()); return; }
            state.stream = stream;
            const types = ['audio/webm;codecs=opus', 'audio/mp4;codecs=mp4a.40.2', 'audio/mp4', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/ogg'];
            const mime = types.find(type => MediaRecorder.isTypeSupported(type));
            const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
            state.recorder = recorder;
            const chunks = [];
            let size = 0;
            recorder.ondataavailable = event => {
                if (generation !== state.generation) return;
                if (event.data?.size) { chunks.push(event.data); size += event.data.size; }
                if (size > 5 * 1024 * 1024) { reset(state); showError(state, 'Voice notes must be at most 5 MB.'); }
            };
            recorder.onerror = () => { reset(state); showError(state, 'Recording failed. Please try again.'); };
            recorder.onstop = async () => {
                if (generation !== state.generation) return;
                releaseMicrophone(state);
                const type = recorder.mimeType || mime || chunks[0]?.type || 'audio/webm';
                const blob = new Blob(chunks, { type });
                if (!blob.size || blob.size > 5 * 1024 * 1024) { reset(state); showError(state, 'Recording is empty or exceeds 5 MB.'); return; }
                state.file = new File([blob], type.includes('mp4') ? 'voice-note.m4a' : type.includes('ogg') ? 'voice-note.ogg' : 'voice-note.webm', { type });
                try {
                    const transfer = new DataTransfer(); transfer.items.add(state.file);
                    state.root.querySelector('input[type="file"]').files = transfer.files;
                } catch (_failure) {
                    reset(state); showError(state, 'This browser cannot attach a recording. Text remarks remain available.'); return;
                }
                state.url = URL.createObjectURL(blob);
                let duration = performance.now() - state.started, levels = fallbackWave;
                let decoder;
                try {
                    decoder = new (window.AudioContext || window.webkitAudioContext)();
                    const decoded = await decoder.decodeAudioData(await blob.arrayBuffer());
                    duration = decoded.duration * 1000;
                    const channel = decoded.getChannelData(0);
                    const peaks = Array.from({ length: 32 }, (_, i) => {
                        let peak = 0;
                        for (let n = Math.floor(channel.length * i / 32); n < channel.length * (i + 1) / 32; n++) peak = Math.max(peak, Math.abs(channel[n]));
                        return peak;
                    });
                    const largest = Math.max(...peaks) || 1;
                    levels = peaks.map(value => Math.max(8, Math.round(90 * value / largest)));
                } catch (_failure) { /* A constant preview waveform remains seekable when decoding is unavailable. */ }
                finally { decoder?.close().catch(() => {}); }
                if (generation !== state.generation || scope.signal.aborted) return;
                state.mode = 'preview';
                state.root.querySelector('[data-voice-recording]').hidden = true;
                const host = state.root.querySelector('[data-voice-preview-bubble]');
                host.replaceChildren(bubble({ url: state.url, duration_ms: duration, waveform: levels }, true));
                state.root.querySelector('[data-voice-preview]').hidden = false;
                button.disabled = false; button.setAttribute('aria-label', 'Re-record voice note');
            };
            state.mode = 'recording'; state.started = performance.now();
            state.root.querySelector('[data-voice-recording]').hidden = false;
            state.root.querySelector('[data-voice-timer]').textContent = '0:00';
            recorder.start(250);
            state.timer = setInterval(() => {
                const elapsed = performance.now() - state.started;
                state.root.querySelector('[data-voice-timer]').textContent = seconds(elapsed / 1000);
                if (elapsed >= 59500) stop(state); // Leave room for the final codec frame within the 60s server limit.
            }, 100);
            try {
                state.context = new (window.AudioContext || window.webkitAudioContext)();
                const source = state.context.createMediaStreamSource(stream), analyser = state.context.createAnalyser();
                analyser.fftSize = 256; source.connect(analyser);
                const samples = new Uint8Array(analyser.fftSize);
                function draw() {
                    if (state.mode !== 'recording') return;
                    analyser.getByteTimeDomainData(samples);
                    waveform(state.root.querySelector('canvas'), Array.from({ length: 32 }, (_, i) => Math.max(8, Math.abs(samples[i * 8] - 128) * 0.7)), 1, '#f87171');
                    state.animation = requestAnimationFrame(draw);
                }
                draw();
            } catch (_failure) { waveform(state.root.querySelector('canvas'), fallbackWave, 1, '#f87171'); }
        } catch (failure) {
            if (generation !== state.generation) return;
            reset(state);
            showError(state, failure.name === 'NotAllowedError' ? 'Microphone permission was denied. Text remarks are still available.' : 'Microphone unavailable. Please try again or use text remarks.');
        }
    }

    root.querySelectorAll('[data-review-voice]').forEach(root => {
        const supported = Boolean(window.MediaRecorder && navigator.mediaDevices?.getUserMedia && window.DataTransfer && window.isSecureContext);
        const state = { root, supported, generation: 0, mode: 'idle', file: null, url: null };
        recorders.set(root, state);
        if (!supported) {
            const button = root.querySelector('[data-voice-action="record"]');
            button.disabled = true; button.title = 'Voice recording requires a supported browser and HTTPS. Text remarks remain available.';
            root.querySelector('.voice-recorder-hint').textContent = button.title;
        }
        const form = root.closest('form');
        if (form) scope.listen(form, 'submit', event => {
            if (form.dataset.voiceSubmitting || ['recording', 'pending', 'finishing'].includes(state.mode)) {
                event.preventDefault();
                if (!form.dataset.voiceSubmitting) showError(state, 'Stop recording before submitting your review.');
                return;
            }
            form.dataset.voiceSubmitting = '1';
            setTimeout(() => form.querySelectorAll('button[type="submit"]').forEach(button => { button.disabled = true; }), 0);
        });
    });
    scope.listen(root, 'click', event => {
        const play = event.target.closest('.voice-play');
        if (play) {
            const audio = play.closest('.review-voice-bubble').querySelector('audio');
            if (!audio.paused) audio.pause();
            else audio.play().catch(() => { play.setAttribute('aria-label', 'Voice note unavailable. Try again.'); });
        }
        const action = event.target.closest('[data-voice-action]');
        if (!action) return;
        const state = recorders.get(action.closest('[data-review-voice]'));
        if (!state) return;
        if (action.dataset.voiceAction === 'record') start(state);
        if (action.dataset.voiceAction === 'stop') stop(state);
        if (['cancel', 'discard'].includes(action.dataset.voiceAction)) reset(state);
    });
    scope.listen(root, 'input', event => {
        if (!event.target.matches('.voice-wave-seek input')) return;
        const seek = event.target, audio = seek.closest('.review-voice-bubble').querySelector('audio');
        const duration = Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : Number(audio.closest('.review-voice-bubble').dataset.duration) / 1000;
        const target = duration * Number(seek.value) / 1000;
        if (audio.readyState) audio.currentTime = target;
        else { audio.addEventListener('loadedmetadata', () => { audio.currentTime = target; }, { once: true }); audio.load(); }
    });
    for (const event of ['play', 'pause', 'ended', 'timeupdate', 'loadedmetadata', 'durationchange']) {
        scope.listen(root, event, event => {
            const audio = event.target;
            if (!audio.matches?.('audio[data-review-voice-audio]')) return;
            if (event.type === 'play') { if (activeAudio && activeAudio !== audio) activeAudio.pause(); activeAudio = audio; }
            paintBubble(audio);
        }, { capture: true });
    }
    function resetWithin(root) {
        for (const state of recorders.values()) if (root.contains(state.root)) reset(state);
        stopPlaybackWithin(root);
    }
    const api = {
        resetWithin, appendBubbles, stopPlaybackWithin,
        suspendWithin(root) {
            for (const state of recorders.values()) if (root.contains(state.root)) {
                if (state.mode === 'recording') stop(state);
                else if (state.mode === 'pending') reset(state);
            }
            root.querySelectorAll('audio[data-review-voice-audio]').forEach(audio => audio.pause());
        },
        file(root) { return recorders.get(root)?.file || null; },
        hasDraft(root) { return Array.from(recorders.values()).some(state => root.contains(state.root) && (state.file || ['pending', 'recording', 'finishing'].includes(state.mode))); },
        ready(root) {
            const state = recorders.get(root);
            if (state && ['pending', 'recording', 'finishing'].includes(state.mode)) { showError(state, 'Stop recording before submitting your review.'); return false; }
            return true;
        },
    };
    if (root === document) window.fabroReviewVoice = api;
    const notes = JSON.parse(root.querySelector('#design-review-voice-notes')?.textContent || '[]');
    root.querySelectorAll('[data-review-voice-history]').forEach(host => appendBubbles(host,
        notes.filter(note => String(note.cycle) === host.dataset.approvalCycle && (!host.dataset.reviewStage || note.stage === host.dataset.reviewStage))));
    scope.listen(document, 'visibilitychange', () => {
        if (document.hidden) for (const state of recorders.values()) {
            if (state.mode === 'recording') stop(state);
            else if (state.mode === 'pending') reset(state);
        }
    });
    scope.listen(window, 'pagehide', () => { recorders.forEach(reset); stopPlaybackWithin(root); });
    scope.onCleanup(() => {
        recorders.forEach(reset);
        stopPlaybackWithin(root);
        if (window.fabroReviewVoice === api) delete window.fabroReviewVoice;
    });
    return api;
};
window.fabroOnPageLoad(() => window.fabroInitReviewVoice(document, window.fabroCreatePageScope()));
})();
