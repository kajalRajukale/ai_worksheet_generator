const form = document.querySelector("#worksheet-form");
const generateButton = document.querySelector("#generate-button");
const formError = document.querySelector("#form-error");
const downloadError = document.querySelector("#download-error");
const subjectSelect = document.querySelector("#subject");
const customSubjectField = document.querySelector("#custom-subject-field");
const customSubjectInput = document.querySelector("#other-subject");
const emptyPreview = document.querySelector("#empty-preview");
const resultPanel = document.querySelector("#worksheet-result");
const previewStatus = document.querySelector("#preview-status");
const answerKeyPreview = document.querySelector("#answer-key-preview");
const questionList = document.querySelector("#question-list");
const answerList = document.querySelector("#answer-list");
const worksheetLibrary = document.querySelector("#worksheet-library");
const libraryEmpty = document.querySelector("#library-empty");
const libraryError = document.querySelector("#library-error");
const saveError = document.querySelector("#save-error");
const saveButton = document.querySelector("#save-worksheet");
const worksheetSearch = document.querySelector("#worksheet-search");
const worksheetSaveStatus = document.querySelector("#worksheet-save-status");
let currentWorksheet = null;
let currentWorksheetId = null;
let librarySearchTimer = null;

subjectSelect.addEventListener("change", () => {
  const isCustom = subjectSelect.value === "Other";
  customSubjectField.hidden = !isCustom;
  customSubjectInput.required = isCustom;
  if (isCustom) customSubjectInput.focus();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearError(formError);

  const selectedTypes = [...form.querySelectorAll('input[name="question_types"]:checked')]
    .map((input) => input.value);
  if (selectedTypes.length === 0) {
    showError(formError, "Choose at least one question type.");
    return;
  }

  const formData = new FormData(form);
  const subject = formData.get("subject");
  const requestBody = {
    subject,
    other_subject: formData.get("other_subject") || "",
    grade: formData.get("grade"),
    topic: formData.get("topic"),
    difficulty: formData.get("difficulty"),
    question_count: Number(formData.get("question_count")),
    question_types: selectedTypes,
    language: formData.get("language"),
    include_answer_key: formData.get("include_answer_key") === "on",
    additional_instructions: formData.get("additional_instructions") || "",
  };

  setGenerating(true);
  previewStatus.textContent = "GENERATING";
  try {
    const response = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "The worksheet could not be generated.");
    currentWorksheetId = result.id;
    currentWorksheet = result.worksheet;
    renderWorksheet(currentWorksheet);
    previewStatus.textContent = "SAVED TO MY WORKSHEETS";
    worksheetSaveStatus.textContent = "SAVED WORKSHEET";
    await loadWorksheetLibrary();
  } catch (error) {
    previewStatus.textContent = "NOT GENERATED";
    showError(formError, error.message || "Could not reach the worksheet service.");
  } finally {
    setGenerating(false);
  }
});

document.querySelector("#new-worksheet").addEventListener("click", () => {
  document.querySelector("#topic").focus();
  document.querySelector("#generator").scrollIntoView({ behavior: "smooth", block: "start" });
});

saveButton.addEventListener("click", saveWorksheet);
document.querySelector("#similar-worksheet").addEventListener("click", createSimilarWorksheet);
document.querySelector("#add-question").addEventListener("click", addQuestion);
questionList.addEventListener("click", deleteQuestion);
resultPanel.addEventListener("input", () => {
  if (currentWorksheetId !== null) worksheetSaveStatus.textContent = "UNSAVED CHANGES";
});
worksheetSearch.addEventListener("input", () => {
  clearTimeout(librarySearchTimer);
  librarySearchTimer = setTimeout(() => loadWorksheetLibrary(worksheetSearch.value.trim()), 180);
});
worksheetLibrary.addEventListener("click", handleLibraryAction);

document.querySelector("#student-pdf").addEventListener("click", () => downloadPDF(false));
document.querySelector("#teacher-pdf").addEventListener("click", () => downloadPDF(true));

loadWorksheetLibrary();

function setGenerating(isGenerating) {
  generateButton.disabled = isGenerating;
  generateButton.classList.toggle("is-loading", isGenerating);
  generateButton.querySelector(".button-label").textContent = isGenerating
    ? "Building your worksheet..."
    : "Generate worksheet";
}

function showError(target, message) {
  target.textContent = message;
  target.hidden = false;
}

function clearError(target) {
  target.textContent = "";
  target.hidden = true;
}

function editableText(text, className, label) {
  const element = document.createElement("span");
  element.className = className;
  element.textContent = text;
  element.contentEditable = "true";
  element.setAttribute("role", "textbox");
  element.setAttribute("aria-label", label);
  return element;
}

function renderWorksheet(worksheet) {
  emptyPreview.hidden = true;
  resultPanel.hidden = false;
  document.querySelector("#worksheet-title").textContent = worksheet.title;
  document.querySelector("#worksheet-grade").textContent = worksheet.grade;
  document.querySelector("#student-name").value = worksheet.student_name || "";
  document.querySelector("#worksheet-date").textContent = new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
  }).format(new Date());
  document.querySelector("#worksheet-meta").textContent = `${worksheet.subject} · ${worksheet.topic} · ${worksheet.difficulty}`;

  const instructions = document.querySelector("#print-instructions");
  instructions.textContent = worksheet.instructions;
  instructions.hidden = !worksheet.instructions;

  questionList.replaceChildren();
  answerList.replaceChildren();
  worksheet.questions.forEach((question, index) => {
    const item = document.createElement("li");
    const title = editableText(question.question, "question-title", `Edit question ${index + 1}`);
    const points = document.createElement("span");
    points.className = "question-points";
    points.textContent = `${question.points} pt${question.points === 1 ? "" : "s"}`;
    item.append(title, document.createTextNode(" "), points);

    if (question.options.length) {
      const options = document.createElement("ol");
      options.className = "option-list";
      options.type = "A";
      question.options.forEach((option, optionIndex) => {
        const optionItem = document.createElement("li");
        optionItem.append(editableText(option, "editable-option", `Edit choice ${optionIndex + 1}`));
        options.append(optionItem);
      });
      item.append(options);
    }

    if (question.pairs.length) {
      const pairs = document.createElement("ol");
      pairs.className = "pair-list";
      question.pairs.forEach((pair, pairIndex) => {
        const pairItem = document.createElement("li");
        const row = document.createElement("span");
        row.className = "match-pair";
        row.append(
          editableText(pair.left, "editable-pair-left", `Edit matching item ${pairIndex + 1}`),
          editableText(pair.right, "editable-pair-right", `Edit matching answer ${pairIndex + 1}`),
        );
        pairItem.append(row);
        pairs.append(pairItem);
      });
      item.append(pairs);
    }
    const removeButton = document.createElement("button");
    removeButton.className = "remove-question-button";
    removeButton.type = "button";
    removeButton.dataset.index = String(index);
    removeButton.textContent = "Remove";
    removeButton.setAttribute("aria-label", `Remove question ${index + 1}`);
    item.append(removeButton);
    questionList.append(item);

    const answerItem = document.createElement("li");
    answerItem.className = "answer-item";
    answerItem.append(editableText(question.answer, "editable-answer", `Edit answer ${index + 1}`));
    if (question.explanation) {
      const explanation = document.createElement("p");
      explanation.className = "answer-explanation";
      explanation.append(editableText(question.explanation, "editable-explanation", `Edit explanation ${index + 1}`));
      answerItem.append(explanation);
    }
    answerList.append(answerItem);
  });

  answerKeyPreview.hidden = !worksheet.include_answer_key;
  document.querySelector("#teacher-pdf").hidden = !worksheet.include_answer_key;
  clearError(saveError);
}

function getEditedWorksheet() {
  const worksheet = structuredClone(currentWorksheet);
  worksheet.title = document.querySelector("#worksheet-title").innerText.trim();
  worksheet.student_name = document.querySelector("#student-name").value.trim();
  worksheet.instructions = document.querySelector("#print-instructions").innerText.trim();
  const questionItems = [...questionList.children];
  worksheet.questions = worksheet.questions.map((question, index) => {
    const item = questionItems[index];
    question.question = item.querySelector(".question-title").innerText.trim();
    question.options = [...item.querySelectorAll(".editable-option")].map((node) => node.innerText.trim());
    question.pairs = [...item.querySelectorAll(".match-pair")].map((row) => ({
      left: row.querySelector(".editable-pair-left").innerText.trim(),
      right: row.querySelector(".editable-pair-right").innerText.trim(),
    }));
    const answerNode = answerList.children[index]?.querySelector(".editable-answer");
    question.answer = answerNode?.innerText.trim() || "";
    const explanationNode = answerList.children[index]?.querySelector(".editable-explanation");
    question.explanation = explanationNode?.innerText.trim() || "";
    return question;
  });
  return worksheet;
}

async function loadWorksheetLibrary(search = "") {
  clearError(libraryError);
  try {
    const url = new URL("/api/worksheets", window.location.origin);
    if (search) url.searchParams.set("q", search);
    const response = await fetch(url);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Saved worksheets could not be loaded.");
    renderWorksheetLibrary(result.worksheets, search);
  } catch (error) {
    showError(libraryError, error.message || "Saved worksheets could not be loaded.");
  }
}

function renderWorksheetLibrary(worksheets, search) {
  worksheetLibrary.replaceChildren();
  document.querySelector("#worksheet-count").textContent =
    `${worksheets.length} ${worksheets.length === 1 ? "worksheet" : "worksheets"}`;
  libraryEmpty.hidden = worksheets.length > 0;
  if (!worksheets.length) {
    libraryEmpty.textContent = search
      ? "No saved worksheets match your search."
      : "Your saved worksheets will appear here after you generate them.";
    return;
  }

  worksheets.forEach((worksheet) => {
    const item = document.createElement("li");
    item.className = "worksheet-card";
    const details = document.createElement("div");
    details.className = "worksheet-card-details";
    const title = document.createElement("h3");
    title.textContent = worksheet.title;
    const metadata = document.createElement("p");
    metadata.textContent = `${worksheet.grade} · ${worksheet.subject} · ${worksheet.topic}`;
    const difficulty = document.createElement("span");
    difficulty.className = "worksheet-card-difficulty";
    difficulty.textContent = `${worksheet.difficulty} · Updated ${new Date(worksheet.updated_at).toLocaleDateString()}`;
    details.append(title, metadata, difficulty);

    const actions = document.createElement("div");
    actions.className = "worksheet-card-actions";
    actions.append(
      libraryActionButton("Open", worksheet.id, "open"),
      libraryActionButton("Create similar", worksheet.id, "similar"),
    );
    item.append(details, actions);
    worksheetLibrary.append(item);
  });
}

function libraryActionButton(label, id, action) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "library-action-button";
  button.dataset.id = String(id);
  button.dataset.action = action;
  button.textContent = label;
  return button;
}

async function handleLibraryAction(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  if (button.dataset.action === "open") {
    await openWorksheet(Number(button.dataset.id));
  } else {
    await loadSimilarSettings(Number(button.dataset.id));
  }
}

async function openWorksheet(id) {
  clearError(saveError);
  try {
    const response = await fetch(`/api/worksheets/${id}`);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Worksheet could not be opened.");
    currentWorksheetId = result.id;
    currentWorksheet = result.worksheet;
    renderWorksheet(currentWorksheet);
    worksheetSaveStatus.textContent = "SAVED WORKSHEET";
    previewStatus.textContent = "SAVED WORKSHEET OPENED";
    document.querySelector("#generator").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showError(libraryError, error.message || "Worksheet could not be opened.");
  }
}

async function loadSimilarSettings(id) {
  clearError(libraryError);
  try {
    const response = await fetch(`/api/worksheets/${id}`);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Worksheet settings could not be loaded.");
    fillWorksheetSettings(result.generation_settings);
    document.querySelector("#generator").scrollIntoView({ behavior: "smooth", block: "start" });
    document.querySelector("#topic").focus();
  } catch (error) {
    showError(libraryError, error.message || "Worksheet settings could not be loaded.");
  }
}

function fillWorksheetSettings(settings) {
  const subjectOption = [...subjectSelect.options].find((option) => option.value === settings.subject);
  subjectSelect.value = subjectOption ? settings.subject : "Other";
  customSubjectField.hidden = subjectSelect.value !== "Other";
  customSubjectInput.required = subjectSelect.value === "Other";
  customSubjectInput.value = subjectSelect.value === "Other" ? settings.subject : "";
  document.querySelector("#grade").value = settings.grade;
  document.querySelector("#topic").value = settings.topic;
  document.querySelector(`#worksheet-form input[name="difficulty"][value="${settings.difficulty}"]`).checked = true;
  document.querySelector("#question-count").value = settings.question_count;
  document.querySelector("#language").value = settings.language;
  document.querySelector("#answer-key").checked = settings.include_answer_key;
  document.querySelector("#additional-instructions").value = settings.additional_instructions;
  form.querySelectorAll('input[name="question_types"]').forEach((input) => {
    input.checked = settings.question_types.includes(input.value);
  });
}

async function createSimilarWorksheet() {
  if (currentWorksheetId === null) return;
  await loadSimilarSettings(currentWorksheetId);
}

async function saveWorksheet() {
  clearError(saveError);
  if (currentWorksheetId === null || currentWorksheet === null) {
    showError(saveError, "Generate or open a saved worksheet before saving changes.");
    return;
  }
  saveButton.disabled = true;
  worksheetSaveStatus.textContent = "SAVING...";
  try {
    const response = await fetch(`/api/worksheets/${currentWorksheetId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ worksheet: getEditedWorksheet() }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Changes could not be saved.");
    currentWorksheetId = result.id;
    currentWorksheet = result.worksheet;
    renderWorksheet(currentWorksheet);
    worksheetSaveStatus.textContent = "CHANGES SAVED";
    previewStatus.textContent = "CHANGES SAVED";
    await loadWorksheetLibrary(worksheetSearch.value.trim());
  } catch (error) {
    worksheetSaveStatus.textContent = "SAVE FAILED";
    showError(saveError, error.message || "Changes could not be saved.");
  } finally {
    saveButton.disabled = false;
  }
}

function addQuestion() {
  if (!currentWorksheet) return;
  const worksheet = getEditedWorksheet();
  if (worksheet.questions.length >= 20) {
    showError(saveError, "A worksheet can contain no more than 20 questions.");
    return;
  }
  worksheet.questions.push({
    type: "short_answer",
    question: `Question ${worksheet.questions.length + 1}: write your question here`,
    options: [],
    pairs: [],
    answer: worksheet.include_answer_key ? "Write the answer here" : "",
    explanation: "",
    points: 1,
  });
  currentWorksheet = worksheet;
  renderWorksheet(currentWorksheet);
  worksheetSaveStatus.textContent = "UNSAVED CHANGES";
}

function deleteQuestion(event) {
  const button = event.target.closest(".remove-question-button");
  if (!button || !currentWorksheet) return;
  const worksheet = getEditedWorksheet();
  if (worksheet.questions.length <= 1) {
    showError(saveError, "A worksheet must contain at least one question.");
    return;
  }
  worksheet.questions.splice(Number(button.dataset.index), 1);
  currentWorksheet = worksheet;
  renderWorksheet(currentWorksheet);
  worksheetSaveStatus.textContent = "UNSAVED CHANGES";
}

async function downloadPDF(includeAnswerKey) {
  clearError(downloadError);
  const buttons = [...document.querySelectorAll(".download-button")];
  buttons.forEach((button) => { button.disabled = true; });
  try {
    const response = await fetch("/api/pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ worksheet: getEditedWorksheet(), include_answer_key: includeAnswerKey }),
    });
    if (!response.ok) {
      const result = await response.json();
      throw new Error(result.error || "The PDF could not be created.");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = includeAnswerKey ? "worksheet-teacher-copy.pdf" : "worksheet-student-copy.pdf";
    link.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    showError(downloadError, error.message || "The PDF could not be downloaded.");
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
  }
}