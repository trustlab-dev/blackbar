// frontend/src/components/viewer/BlockingRedactionsBanner.tsx
//
// Lists the redactions that block export and release. Only approved
// redactions are burned in; anything unresolved (proposed, contested,
// pending, no status) makes export return 409 and the release package mark
// the document failed (backend/src/utils/redaction_records.py, DOC-13).
import React from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Collapse from '@mui/material/Collapse';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemText from '@mui/material/ListItemText';
import Typography from '@mui/material/Typography';
import { describeBlockingStatus } from '../../utils/redactionStatus';

export interface BlockingRedaction {
  id?: string;
  page: number;
  status?: string;
  type?: string;
  categoryName?: string;
  notes?: string;
}

export const LEGACY_NO_ID_HINT =
  'This older redaction has no ID, so it is read-only here. Ask an administrator to migrate it.';

/** Why a blocking redaction cannot be approved from the viewer, or null if it can. */
export function reviewHint(redaction: BlockingRedaction): string | null {
  if (!redaction.id) return LEGACY_NO_ID_HINT;
  const status = String(redaction.status ?? '').toLowerCase();
  if (status === 'contested') return 'Contested: resolve the contest before export or release.';
  if (redaction.type === 'proposed') return null;
  return 'Not a proposal, so it cannot be approved here. Delete and redraw it, or ask an administrator.';
}

interface Props {
  redactions: BlockingRedaction[];
  expanded: boolean;
  onToggle: () => void;
  onApprove: (redaction: BlockingRedaction) => void;
  onReject: (redaction: BlockingRedaction) => void;
  onGoTo: (redaction: BlockingRedaction) => void;
  busyId?: string | null;
}

const BlockingRedactionsBanner: React.FC<Props> = ({
  redactions,
  expanded,
  onToggle,
  onApprove,
  onReject,
  onGoTo,
  busyId,
}) => {
  if (redactions.length === 0) return null;
  const count = redactions.length;

  return (
    <Box data-testid="blocking-redactions" sx={{ borderBottom: '1px solid var(--border-default)' }}>
      <Alert
        severity="warning"
        sx={{ borderRadius: 0, py: 0 }}
        action={
          <Button color="inherit" size="small" onClick={onToggle}>
            {expanded ? 'Hide' : 'Review'}
          </Button>
        }
      >
        <strong>
          {count} redaction{count !== 1 ? 's' : ''} awaiting review.
        </strong>{' '}
        Only approved redactions are applied. Export and release are blocked until each one is
        approved or rejected.
      </Alert>
      <Collapse in={expanded} unmountOnExit>
        <List dense sx={{ maxHeight: 220, overflow: 'auto', py: 0, bgcolor: 'var(--bg-secondary, #fff)' }}>
          {redactions.map((redaction, index) => {
            const hint = reviewHint(redaction);
            const busy = Boolean(redaction.id) && busyId === redaction.id;
            return (
              <ListItem
                key={redaction.id ?? `legacy-${index}`}
                divider
                secondaryAction={
                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <Button size="small" onClick={() => onGoTo(redaction)}>
                      Show
                    </Button>
                    {!hint && (
                      <>
                        <Button
                          size="small"
                          variant="contained"
                          color="success"
                          disabled={busy}
                          onClick={() => onApprove(redaction)}
                        >
                          Approve
                        </Button>
                        <Button
                          size="small"
                          variant="outlined"
                          color="error"
                          disabled={busy}
                          onClick={() => onReject(redaction)}
                        >
                          Reject
                        </Button>
                      </>
                    )}
                  </Box>
                }
              >
                <ListItemText
                  sx={{ pr: hint ? 10 : 30 }}
                  primary={`Page ${redaction.page} · ${redaction.categoryName || 'No category'} · ${describeBlockingStatus(redaction)}`}
                  secondary={
                    <>
                      {redaction.notes && (
                        <Typography component="span" variant="caption" sx={{ display: 'block' }}>
                          {redaction.notes}
                        </Typography>
                      )}
                      {hint && (
                        <Typography component="span" variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                          {hint}
                        </Typography>
                      )}
                    </>
                  }
                />
              </ListItem>
            );
          })}
        </List>
      </Collapse>
    </Box>
  );
};

export default BlockingRedactionsBanner;
