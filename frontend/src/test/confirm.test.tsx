import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ConfirmDialog } from '../components/ConfirmDialog';

describe('irreversible trading confirmations', () => {
  it('requires acknowledgment, second step and exact written Live confirmation', async () => {
    const user = userEvent.setup();
    const action = vi.fn().mockResolvedValue(undefined);
    const close = vi.fn();
    render(<ConfirmDialog kind="live" onConfirm={action} onClose={close} />);
    expect(screen.getByRole('button', { name: 'Continua' })).toBeDisabled();
    await user.click(screen.getByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: 'Continua' }));
    const input = screen.getByRole('textbox');
    await user.type(input, 'avvia live');
    expect(screen.getByRole('button', { name: 'Avvia con fondi reali' })).toBeDisabled();
    expect(action).not.toHaveBeenCalled();
    await user.clear(input);
    await user.type(input, 'AVVIA LIVE');
    await user.click(screen.getByRole('button', { name: 'Avvia con fondi reali' }));
    await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
    expect(close).toHaveBeenCalled();
  });
  it('requires distinct written Close All confirmation', async () => {
    const user = userEvent.setup();
    const action = vi.fn().mockResolvedValue(undefined);
    render(<ConfirmDialog kind="close" onConfirm={action} onClose={vi.fn()} />);
    await user.click(screen.getByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: 'Continua' }));
    await user.type(screen.getByRole('textbox'), 'AVVIA LIVE');
    expect(screen.getByRole('button', { name: 'Conferma chiusura' })).toBeDisabled();
    await user.clear(screen.getByRole('textbox'));
    await user.type(screen.getByRole('textbox'), 'CHIUDI TUTTO');
    await user.click(screen.getByRole('button', { name: 'Conferma chiusura' }));
    expect(action).toHaveBeenCalledTimes(1);
  });
  it('shows rejected operations and leaves the dialog open', async () => {
    const user = userEvent.setup();
    const close = vi.fn();
    render(
      <ConfirmDialog
        kind="live"
        onConfirm={vi.fn().mockRejectedValue(new Error('LIVE bloccato dal backend.'))}
        onClose={close}
      />,
    );
    await user.click(screen.getByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: 'Continua' }));
    await user.type(screen.getByRole('textbox'), 'AVVIA LIVE');
    await user.click(screen.getByRole('button', { name: 'Avvia con fondi reali' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('LIVE bloccato'));
    expect(close).not.toHaveBeenCalled();
  });
  it('canceling a confirmation never invokes the trading action', async () => {
    const user = userEvent.setup();
    const action = vi.fn();
    const close = vi.fn();
    render(<ConfirmDialog kind="close" onConfirm={action} onClose={close} />);
    await user.click(screen.getByRole('button', { name: 'Annulla' }));
    expect(close).toHaveBeenCalledTimes(1);
    expect(action).not.toHaveBeenCalled();
  });
});
