document.addEventListener("DOMContentLoaded", () => {
    const scannerContainer = document.getElementById("scanner-container");
    const video = document.getElementById("video");
    const canvas = document.getElementById("canvas");
    const statusText = document.getElementById("status-text");
    const scanBorder = document.getElementById("scan-border");
    const scanLine = document.getElementById("scan-line");

    if (!scannerContainer || !video || !canvas || !statusText || !scanBorder || !scanLine) {
        return;
    }

    const apiEndpoint = scannerContainer.dataset.apiEndpoint || "/api/biometric-auth";
    const pollInterval = Number.parseInt(scannerContainer.dataset.pollInterval || "1500", 10);
    const captureSize = Number.parseInt(scannerContainer.dataset.captureSize || "160", 10);
    const context = canvas.getContext("2d");
    let mediaStream = null;
    let active = true;
    let requestInFlight = false;
    let pollTimer = null;
    const frameBurstCount = Number.parseInt(scannerContainer.dataset.frameBurstCount || "5", 10);
    const frameBurstDelay = Number.parseInt(scannerContainer.dataset.frameBurstDelay || "120", 10);

    function setStatus(message, iconClass, borderColor, loaderVisible = false) {
        scannerContainer.classList.toggle("is-busy", loaderVisible);
        statusText.innerHTML = `${loaderVisible ? '<span class="scan-loader"></span>' : ''}<i class="fas ${iconClass} status-icon"></i>${message}`;
        scanBorder.style.borderColor = borderColor;
    }

    function stopCamera() {
        if (mediaStream) {
            mediaStream.getTracks().forEach((track) => track.stop());
            mediaStream = null;
        }
    }

    async function fetchChallengeNonce() {
        const response = await fetch("/api/biometric-challenge", { cache: "no-store" });
        if (!response.ok) {
            throw new Error("Unable to fetch biometric challenge");
        }

        const result = await response.json();
        return result;
    }

    function drawCenteredCrop() {
        const sourceWidth = video.videoWidth || 320;
        const sourceHeight = video.videoHeight || 240;
        const cropSize = Math.min(sourceWidth, sourceHeight);
        const cropX = Math.max(0, Math.floor((sourceWidth - cropSize) / 2));
        const cropY = Math.max(0, Math.floor((sourceHeight - cropSize) / 2));

        canvas.width = Number.isFinite(captureSize) ? captureSize : 160;
        canvas.height = Number.isFinite(captureSize) ? captureSize : 160;
        context.drawImage(video, cropX, cropY, cropSize, cropSize, 0, 0, canvas.width, canvas.height);
    }

    function captureFrameData() {
        drawCenteredCrop();
        return canvas.toDataURL("image/jpeg", 0.9);
    }

    async function captureFrameBurst() {
        const frames = [];
        for (let index = 0; index < Math.max(3, frameBurstCount); index += 1) {
            frames.push(captureFrameData());
            if (index < frameBurstCount - 1) {
                await new Promise((resolve) => window.setTimeout(resolve, Math.max(60, frameBurstDelay)));
            }
        }

        return frames;
    }

    function finishSuccess(username) {
        active = false;
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
        stopCamera();
        scanLine.style.display = "none";
        setStatus(` Welcome, ${username}`, "fa-check-circle text-success", "#28a745", false);

        window.setTimeout(() => {
            window.location.href = "/";
        }, 1500);
    }

    async function captureAndSendFrame() {
        if (!active || requestInFlight || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
            return;
        }

        requestInFlight = true;
        scannerContainer.classList.add("is-busy");
        setStatus("Scanning...", "fa-spinner fa-spin text-white", "rgba(255,255,255,0.25)", true);

        try {
            const challengePayload = await fetchChallengeNonce();
            setStatus(challengePayload.prompt || "Scanning...", "fa-user-check text-primary", "rgba(0, 123, 255, 0.45)", true);
            const frames = await captureFrameBurst();

            const response = await fetch(apiEndpoint, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    image_b64: frames[frames.length - 1],
                    frames_b64: frames,
                    nonce: challengePayload.nonce,
                    challenge: challengePayload.challenge,
                }),
            });

            if (!response.ok) {
                const errorResult = await response.json().catch(() => ({}));
                throw new Error(errorResult.detail || `Biometric auth failed (${response.status})`);
            }

            const result = await response.json();

            if (result.status === "success") {
                finishSuccess(result.user || "Guest");
                return;
            }

            if (result.status === "unknown") {
                setStatus("Face not recognized", "fa-user-slash text-warning", "rgba(255, 193, 7, 0.5)", false);
                return;
            }

            if (result.status === "liveness_failed") {
                setStatus(result.message || "Liveness check failed", "fa-user-shield text-warning", "rgba(255, 193, 7, 0.5)", false);
                return;
            }

            if (result.status === "admin_required") {
                setStatus(result.message || "Privileged accounts must use password and admin key.", "fa-user-shield text-warning", "rgba(255, 193, 7, 0.5)", false);
                return;
            }

            setStatus("Scanning...", "fa-spinner fa-spin text-white", "rgba(255,255,255,0.25)", true);
        } catch (error) {
            console.error("[Biometric Scan] API error:", error);
            setStatus(error.message || "Connection error", "fa-wifi text-danger", "rgba(220, 53, 69, 0.5)", false);
        } finally {
            requestInFlight = false;
        }
    }

    async function startCamera() {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            setStatus("Camera not supported", "fa-video-slash text-danger", "rgba(220, 53, 69, 0.5)", false);
            return;
        }

        try {
            mediaStream = await navigator.mediaDevices.getUserMedia({
                video: {
                    facingMode: { ideal: "user" },
                },
                audio: false,
            });

            video.srcObject = mediaStream;
            await video.play();

            setStatus("Look at the camera", "fa-circle-notch fa-spin text-primary", "rgba(0, 123, 255, 0.45)", true);
            pollTimer = window.setInterval(captureAndSendFrame, Number.isFinite(pollInterval) ? pollInterval : 1500);
            await captureAndSendFrame();
        } catch (error) {
            console.error("[Biometric Scan] Camera error:", error);
            setStatus("Camera permission denied", "fa-exclamation-triangle text-danger", "rgba(220, 53, 69, 0.5)", false);
        }
    }

    window.addEventListener("beforeunload", stopCamera);
    startCamera();
});