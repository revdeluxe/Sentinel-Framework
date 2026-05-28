document.addEventListener("DOMContentLoaded", () => {
    const widgets = document.querySelectorAll("[data-face-enroll-widget]");

    widgets.forEach((widget) => {
        const video = widget.querySelector("[data-face-enroll-video]");
        const canvas = widget.querySelector("[data-face-enroll-canvas]");
        const statusText = widget.querySelector("[data-face-enroll-status]");
        const startButton = widget.querySelector("[data-face-enroll-start]");
        const enrollButton = widget.querySelector("[data-face-enroll-submit]");
        const stopButton = widget.querySelector("[data-face-enroll-stop]");
        const targetSelect = widget.querySelector("[data-face-enroll-target]");
        const selectedNameLabel = widget.querySelector("[data-face-enroll-selected-name]");
        const modalButtons = document.querySelectorAll(".user-select-option");

        if (!video || !canvas || !statusText || !startButton || !enrollButton) {
            return;
        }

        const apiEndpoint = widget.dataset.faceEnrollApi || "/api/biometric-enroll";
        const captureSize = Number.parseInt(widget.dataset.captureSize || "160", 10);
        const targetUserId = widget.dataset.faceEnrollUserId || "";
        const context = canvas.getContext("2d");
        let mediaStream = null;

        function updateSelectedUser(label, userId) {
            if (targetSelect) {
                targetSelect.value = userId || "";
            }

            if (selectedNameLabel) {
                selectedNameLabel.textContent = label || "No user selected";
                selectedNameLabel.className = label ? "badge badge-success" : "badge badge-secondary";
            }
        }

        function setStatus(message, tone = "muted") {
            statusText.textContent = message;
            statusText.className = `text-${tone} small mb-0`;
        }

        function stopCamera() {
            if (mediaStream) {
                mediaStream.getTracks().forEach((track) => track.stop());
                mediaStream = null;
            }
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

        async function startCamera() {
            try {
                if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                    throw new Error("Camera not supported in this browser.");
                }

                mediaStream = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode: { ideal: "user" } },
                    audio: false,
                });

                video.srcObject = mediaStream;
                await video.play();
                setStatus("Camera ready. Center your face and enroll.", "info");
                enrollButton.disabled = false;
                startButton.disabled = true;
                if (stopButton) {
                    stopButton.disabled = false;
                }
            } catch (error) {
                console.error("[Face Enroll] Camera error:", error);
                enrollButton.disabled = false;
                startButton.disabled = false;
                if (stopButton) {
                    stopButton.disabled = true;
                }
                setStatus(
                    error.name === "NotAllowedError"
                        ? "Camera permission denied"
                        : error.message || "Unable to start camera",
                    "danger"
                );
            }
        }

        async function enrollFace() {
            if (!video || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
                setStatus("Camera is not ready yet.", "warning");
                return;
            }

            drawCenteredCrop();

            const payload = {
                image_b64: canvas.toDataURL("image/jpeg", 0.9),
            };

            const selectedUserId = targetSelect && targetSelect.value ? targetSelect.value : targetUserId;
            if (selectedUserId) {
                payload.user_id = Number.parseInt(selectedUserId, 10);
            } else if (!targetUserId) {
                setStatus("Select a user before enrolling.", "warning");
                enrollButton.disabled = false;
                startButton.disabled = false;
                return;
            }

            enrollButton.disabled = true;
            startButton.disabled = true;
            setStatus("Enrolling face...", "primary");

            try {
                const response = await fetch(apiEndpoint, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify(payload),
                });

                const result = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(result.detail || `Enrollment failed (${response.status})`);
                }

                setStatus(`Enrollment saved${result.face_data_id ? ` (#${result.face_data_id})` : ""}.`, "success");
            } catch (error) {
                console.error("[Face Enroll] API error:", error);
                setStatus(error.message || "Enrollment failed.", "danger");
            } finally {
                enrollButton.disabled = false;
                startButton.disabled = false;
            }
        }

        startButton.addEventListener("click", () => {
            if (!mediaStream) {
                startCamera();
            }
        });

        enrollButton.addEventListener("click", enrollFace);

        if (stopButton) {
            stopButton.addEventListener("click", () => {
                stopCamera();
                enrollButton.disabled = true;
                stopButton.disabled = true;
                setStatus("Camera stopped.", "muted");
            });
        }

        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            setStatus("Camera not supported in this browser.", "danger");
            enrollButton.disabled = true;
            startButton.disabled = true;
            return;
        }

        modalButtons.forEach((button) => {
            button.addEventListener("click", () => {
                const userId = button.dataset.userId || "";
                const userLabel = button.dataset.userLabel || "";
                updateSelectedUser(userLabel, userId);
                const modalElement = document.getElementById("faceEnrollUserModal");
                if (modalElement && window.jQuery) {
                    window.jQuery(modalElement).modal("hide");
                }
                setStatus(userLabel ? `Selected ${userLabel}.` : "No user selected.", "info");
            });
        });

        enrollButton.disabled = false;
        if (stopButton) {
            stopButton.disabled = true;
        }
        updateSelectedUser(targetSelect && targetSelect.value ? targetSelect.value : "", targetSelect && targetSelect.value ? targetSelect.value : "");
        setStatus("Click Open Camera to begin enrollment.", "info");
        window.addEventListener("beforeunload", stopCamera);
    });
});