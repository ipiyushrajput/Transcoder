import React from 'react'
import {
  Box, Card, CardContent, Typography, Switch, FormControlLabel,
  TextField, Alert, Chip, Grid,
} from '@mui/material'
import CampaignIcon from '@mui/icons-material/Campaign'

const SAMPLE_SCC = `<?xml version='1.0' encoding='utf8'?>
<SignalProcessingNotification xmlns="urn:cablelabs:iptvservices:esam:xsd:signal:1"
  xmlns:sig="urn:cablelabs:md:xsd:signaling:3.0"
  xmlns:common="urn:cablelabs:iptvservices:esam:xsd:common:1"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  acquisitionPointIdentity="ExampleESAM">
  <common:BatchInfo batchId="1">
    <common:Source xsi:type="content:MovieType" />
  </common:BatchInfo>
  <!-- CUE-OUT at 510s -->
  <ResponseSignal acquisitionPointIdentity="ExampleESAM" acquisitionSignalID="1" signalPointID="510.08" action="create">
    <sig:NPTPoint nptPoint="510.08" />
    <sig:SCTE35PointDescriptor spliceCommandType="06">
      <sig:SegmentationDescriptorInfo segmentEventId="1" segmentTypeId="52" upidType="09" upid="1" duration="PT30S" segmentNumber="1" segmentsExpected="01" />
    </sig:SCTE35PointDescriptor>
  </ResponseSignal>
  <ConditioningInfo acquisitionSignalIDRef="1" startOffset="PT510S" duration="PT30S" />
  <!-- CUE-IN at 540s -->
  <ResponseSignal acquisitionPointIdentity="ExampleESAM" acquisitionSignalID="2" signalPointID="540.00" action="create">
    <sig:NPTPoint nptPoint="540.00" />
    <sig:SCTE35PointDescriptor spliceCommandType="06">
      <sig:SegmentationDescriptorInfo segmentEventId="1" segmentTypeId="53" upidType="09" upid="2" />
    </sig:SCTE35PointDescriptor>
  </ResponseSignal>
</SignalProcessingNotification>`

export default function AdSignaling({ value, onChange }) {
  const enabled = value?.esam_enabled || false

  const set = (field, val) => onChange({ ...value, [field]: val })

  return (
    <Card>
      <CardContent>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
          <Typography variant="h6" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Box component="span" sx={{ width: 24, height: 24, borderRadius: '50%', bgcolor: 'primary.main', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700 }}>4</Box>
            Ad Signaling (ESAM)
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            {enabled && <Chip label="Enabled" color="warning" size="small" icon={<CampaignIcon />} />}
            <FormControlLabel
              control={<Switch checked={enabled} onChange={(e) => set('esam_enabled', e.target.checked)} color="warning" />}
              label="Enable ESAM"
            />
          </Box>
        </Box>

        {!enabled ? (
          <Alert severity="info">
            Enable ESAM to inject CUE-OUT / CUE-IN markers into HLS variant playlists for dynamic ad insertion.
          </Alert>
        ) : (
          <Box>
            <Alert severity="warning" sx={{ mb: 2 }}>
              ESAM markers are injected into HLS variant playlists after transcoding completes.
              Segment type ID 52 = CUE-OUT (ad start), 53 = CUE-IN (content resume).
            </Alert>

            <Grid container spacing={2}>
              <Grid item xs={12}>
                <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
                  Signal Processing Notification (SCC XML) *
                </Typography>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                  Defines CUE-OUT and CUE-IN points with NPT timestamps and segmentTypeId (52=out, 53=in)
                </Typography>
                <TextField
                  fullWidth multiline rows={12} size="small"
                  placeholder={SAMPLE_SCC}
                  value={value?.esam_scc_xml || ''}
                  onChange={(e) => set('esam_scc_xml', e.target.value)}
                  sx={{ fontFamily: 'monospace', '& .MuiInputBase-input': { fontSize: 11, fontFamily: 'monospace' } }}
                />
              </Grid>

              <Grid item xs={12}>
                <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
                  Manifest Confirm Condition (MCC XML) — Optional
                </Typography>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                  Optional: defines EXT-X-ASSET tags and other manifest modifications
                </Typography>
                <TextField
                  fullWidth multiline rows={6} size="small"
                  placeholder="<?xml version='1.0'?><ns2:ManifestConfirmConditionNotification ...>"
                  value={value?.esam_mcc_xml || ''}
                  onChange={(e) => set('esam_mcc_xml', e.target.value)}
                  sx={{ '& .MuiInputBase-input': { fontSize: 11, fontFamily: 'monospace' } }}
                />
              </Grid>
            </Grid>

            <Box sx={{ mt: 2, p: 1.5, bgcolor: 'rgba(255,152,0,0.07)', borderRadius: 1, border: '1px solid rgba(255,152,0,0.2)' }}>
              <Typography variant="caption" sx={{ fontWeight: 700, display: 'block', mb: 0.5 }}>How it works:</Typography>
              <Typography variant="caption" color="text.secondary">
                1. After FFmpeg completes, the ESAM SCC XML is parsed for ResponseSignal elements<br />
                2. Each signal's NPT timestamp is mapped to the nearest HLS segment<br />
                3. segmentTypeId=52 → #EXT-X-CUE-OUT:&lt;duration&gt; inserted before that segment<br />
                4. segmentTypeId=53 → #EXT-X-CUE-IN inserted before that segment<br />
                5. Intermediate segments get #EXT-X-CUE-OUT-CONT:&lt;elapsed&gt;/&lt;duration&gt;
              </Typography>
            </Box>
          </Box>
        )}
      </CardContent>
    </Card>
  )
}
