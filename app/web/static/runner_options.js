// Renders runner-specific option inputs next to an LLM-runner <select>.
// window.LLM_RUNNER_OPTIONS maps runner name -> options schema
// ([{name, label, type, default}, ...]). Stored values are applied only while
// the select still shows the runner they were saved for; switching runners
// resets the inputs to that runner's defaults.
function initRunnerOptions(selectName, containerId, existingValues, initialRunner) {
  const select = document.querySelector('select[name="' + selectName + '"]');
  const container = document.getElementById(containerId);
  if (!select || !container) return;

  function render() {
    const schema = (window.LLM_RUNNER_OPTIONS || {})[select.value] || [];
    container.innerHTML = "";
    if (!schema.length) {
      container.innerHTML = '<p class="muted">No options for this runner.</p>';
      return;
    }
    schema.forEach(function (opt) {
      const label = document.createElement("label");
      label.className = "runner-option";
      label.appendChild(document.createTextNode(opt.label + " "));
      const input = document.createElement("input");
      input.type = opt.type === "number" ? "number" : "text";
      if (input.type === "number") input.step = "any";
      input.name = selectName + "_opt_" + opt.name;
      input.placeholder = opt.default ? String(opt.default) : "(empty = ignored)";
      const stored = select.value === initialRunner ? existingValues[opt.name] : undefined;
      if (stored !== undefined && stored !== null && stored !== "") {
        input.value = stored;
      } else if (opt.default) {
        input.value = opt.default;
      }
      label.appendChild(input);
      container.appendChild(label);
    });
  }

  select.addEventListener("change", render);
  render();
}
