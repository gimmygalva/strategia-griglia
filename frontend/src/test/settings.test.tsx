import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Settings } from '../components/Settings';
import { api } from '../lib/api';
import { readyState } from './fixtures';

vi.mock('../lib/api', () => ({
  api: { config: vi.fn(), credentials: vi.fn(), connect: vi.fn() },
  ApiError: class extends Error {},
}));
beforeEach(() => {
  vi.mocked(api.config).mockReset().mockResolvedValue({ config: readyState().config });
});

describe('settings configuration', () => {
  it('validates cross-field recovery exposure before submitting config', async () => {
    const user = userEvent.setup();
    render(<Settings state={readyState()} backendOnline refresh={vi.fn()} onWizard={vi.fn()} />);
    const navigation = screen.getByLabelText('Sezioni impostazioni');
    await user.click(within(navigation).getByRole('button', { name: 'Rischio' }));
    const input = screen.getByLabelText('Esposizione Recovery massima');
    await user.clear(input);
    await user.type(input, '6000');
    await user.click(screen.getByRole('button', { name: 'Salva impostazioni' }));
    expect(screen.getByRole('alert')).toHaveTextContent('non può superare');
    expect(api.config).not.toHaveBeenCalled();
  });
  it('saves full validated config with edited decimal string and all existing fields', async () => {
    const user = userEvent.setup();
    const refresh = vi.fn().mockResolvedValue(undefined);
    render(<Settings state={readyState()} backendOnline refresh={refresh} onWizard={vi.fn()} />);
    await user.click(
      within(screen.getByLabelText('Sezioni impostazioni')).getByRole('button', { name: 'Grid' }),
    );
    const input = screen.getByLabelText('Importo per ordine');
    await user.clear(input);
    await user.type(input, '250.125');
    await user.click(screen.getByRole('button', { name: 'Salva impostazioni' }));
    await waitFor(() =>
      expect(api.config).toHaveBeenCalledWith({
        ...readyState().config,
        order_size_usdt: '250.125',
      }),
    );
    expect(screen.getByRole('status')).toHaveTextContent('validate dal backend');
  });
  it('retains unsaved edits while realtime server config updates arrive', async () => {
    const user = userEvent.setup();
    const props = { backendOnline: true, refresh: vi.fn(), onWizard: vi.fn() };
    const { rerender } = render(<Settings state={readyState()} {...props} />);
    await user.click(
      within(screen.getByLabelText('Sezioni impostazioni')).getByRole('button', { name: 'Grid' }),
    );
    const input = screen.getByLabelText('Importo per ordine');
    await user.clear(input);
    await user.type(input, '200');
    rerender(
      <Settings
        state={readyState({ config: { ...readyState().config, order_size_usdt: '150' } })}
        {...props}
      />,
    );
    expect(input).toHaveValue(200);
  });
});
