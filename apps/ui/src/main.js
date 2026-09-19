// No provider credentials here. This mock-only scaffold is intentionally minimal.
import events from '../../../mocks/agent-events.json';
const status = document.querySelector('#status');
const list = document.querySelector('#events');
document.querySelector('#demo').addEventListener('click', async () => {
  list.replaceChildren();
  for (const event of events) {
    status.textContent = event.payload.message ?? event.payload.status;
    const item = document.createElement('li');
    item.textContent = status.textContent;
    list.append(item);
    await new Promise(resolve => setTimeout(resolve, 300));
  }
});
