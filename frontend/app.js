// Configuration
        const API_ENDPOINT = 'https://hkj8c4zag9.execute-api.us-east-1.amazonaws.com/prod/submit';

        // Elements
        const fileInput = document.getElementById('fileInput');
        const dropZone = document.getElementById('dropZone');
        const submitBtn = document.getElementById('submitBtn');
        const btnText = document.getElementById('btnText');
        const resultDiv = document.getElementById('result');
        const loadingSpinner = document.getElementById('loadingSpinner');
        const treatmentTypeInput = document.getElementById('treatmentType');
        const insuranceSelect = document.getElementById('insuranceSelect');
        const patientNameInput = document.getElementById('patientName');

        // State
        let selectedFile = null;

        // Event Listeners
        fileInput.addEventListener('change', handleFileSelect);
        dropZone.addEventListener('click', () => fileInput.click());
        submitBtn.addEventListener('click', submitForApproval);

        // Drag & Drop Handlers
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, preventDefaults, false);
            dropZone.addEventListener(eventName, highlightDropZone, false);
        });

        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }

        function highlightDropZone(e) {
            if (e.type === 'dragenter' || e.type === 'dragover') {
                dropZone.style.borderColor = '#4facfe';
                dropZone.style.background = 'linear-gradient(135deg, #ebf8ff 0%, #bee3f8 100%)';
            } else {
                dropZone.style.borderColor = '#cbd5e0';
                dropZone.style.background = 'linear-gradient(135deg, #f7fafc 0%, #edf2f7 100%)';
            }
        }

        function handleFileSelect(e) {
            selectedFile = e.target.files[0];
            updateDropZoneUI();
        }

        function updateDropZoneUI() {
            if (selectedFile) {
                dropZone.innerHTML = `
                    <span style="font-size: 32px; margin-bottom: 12px; display: block;">✅</span>
                    <p style="color: #4facfe; font-weight: 600;">Selected: ${selectedFile.name}</p>
                `;
            } else {
                dropZone.innerHTML = `
                    <span style="font-size: 48px; margin-bottom: 16px; display: block;">📄</span>
                    <p>Drag & drop medical documents here or click to browse</p>
                `;
            }
        }

        // Handle file drop
        dropZone.addEventListener('drop', (e) => {
            const dt = e.dataTransfer;
            if (dt.files.length > 0) {
                selectedFile = dt.files[0];
                fileInput.files = dt.files;
                updateDropZoneUI();
            }
        });

        async function submitForApproval() {
            // Validate required fields
            if (!treatmentTypeInput.value) {
                showResult('Please specify the treatment type', 'error');
                return;
            }

            if (!selectedFile) {
                showResult('Please select a medical document', 'error');
                return;
            }

            // Show loading state
            submitBtn.disabled = true;
            btnText.style.display = 'none';
            loadingSpinner.style.display = 'block';
            resultDiv.style.display = 'none';

            try {
                // Convert file to base64
                const base64Data = await readFileAsBase64(selectedFile);
                
                // Prepare payload
                const payload = {
                    document: base64Data,
                    insurance_type: insuranceSelect.value,
                    treatment_type: treatmentTypeInput.value,
                    patient_name: patientNameInput.value || undefined
                };

                // Call API
                const response = await fetch(API_ENDPOINT, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                const data = await response.json();

                if (response.ok) {
                    displayResults(data);
                } else {
                    throw new Error(data.error || 'Failed to process request');
                }
            } catch (error) {
                console.error('Error:', error);
                showResult(`Error: ${error.message}`, 'error');
            } finally {
                submitBtn.disabled = false;
                btnText.style.display = 'inline';
                loadingSpinner.style.display = 'none';
            }
        }

        function readFileAsBase64(file) {
            return new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = (event) => resolve(event.target.result.split(',')[1]);
                reader.onerror = (error) => reject(error);
                reader.readAsDataURL(file);
            });
        }

        function displayResults(data) {
            resultDiv.style.display = 'block';
            
            if (data.ai_analysis && data.ai_analysis.decision) {
                const analysis = data.ai_analysis;
                
                if (analysis.decision.includes('APPROVED')) {
                    resultDiv.className = 'result approved';
                    resultDiv.innerHTML = `
                        <h3>✅ APPROVED (${analysis.confidence_score}% confidence)</h3>
                        <p><strong>Reason:</strong> ${analysis.reason}</p>
                        <p><strong>Request ID:</strong> ${data.request_id}</p>
                        ${analysis.missing_documentation.length ? `
                        <div class="notes">
                            <p><strong>Note:</strong> ${analysis.missing_documentation.join(', ')}</p>
                        </div>
                        ` : ''}
                    `;
                } else {
                    resultDiv.className = 'result denied';
                    resultDiv.innerHTML = `
                        <h3>❌ DENIED (${analysis.confidence_score}% confidence)</h3>
                        <p><strong>Reason:</strong> ${analysis.reason}</p>
                        ${analysis.alternative_treatments.length ? `
                        <p><strong>Alternatives:</strong> ${analysis.alternative_treatments.join(', ')}</p>
                        ` : ''}
                        ${analysis.appeal_guidance ? `
                        <p><strong>Appeal Guidance:</strong> ${analysis.appeal_guidance}</p>
                        ` : ''}
                        <p><strong>Request ID:</strong> ${data.request_id}</p>
                    `;
                }
            } else {
                // Fallback for basic analysis
                resultDiv.className = 'result processing';
                resultDiv.innerHTML = `
                    <h3>⏳ PROCESSING</h3>
                    <p>Initial analysis complete. AI review pending.</p>
                    <p><strong>Approval Probability:</strong> ${Math.round(data.approval_probability * 100)}%</p>
                    <p><strong>Next Steps:</strong></p>
                    <ul>${data.next_steps.map(step => `<li>${step}</li>`).join('')}</ul>
                `;
            }
        }

        function showResult(message, type = 'info') {
            resultDiv.style.display = 'block';
            resultDiv.className = type === 'error' ? 'result denied' : 'result processing';
            resultDiv.innerHTML = `<h3>${type === 'error' ? '❌' : '⚠️'}</h3><p>${message}</p>`;
        }