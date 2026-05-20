import { Box, Paper, Button, Card, FormControl, FormLabel, Grid, Select, TextField, Typography, TableContainer, Table, TableHead, TableRow, TableBody, Alert, Divider, MenuItem, IconButton, Tooltip, FormHelperText } from "@mui/material";
import React, { useEffect, useState } from "react";
import { styled } from "@mui/material/styles";
import TableCell, { tableCellClasses } from "@mui/material/TableCell";
import ClearIcon from "@mui/icons-material/Clear";
import DeleteForeverIcon from "@mui/icons-material/DeleteForever";
import cloneDeep from "lodash/cloneDeep";
import { environment } from "../../../Services/Config";
import globalService from "../../../Services/globalServices";
import AddCircleIcon from "@mui/icons-material/AddCircle";
import CancelIcon from "@mui/icons-material/Cancel";
import PublishIcon from "@mui/icons-material/Publish";
import SnackbarClass from "../../Snackbar/snackbar";

export default function AddEvent() {
	const [variantsInputData, setVariantsInputData] = useState({
		videoCodec: "",
		resolution: "",
		videoBitrate: "",
		profile: "",
		level: "",
		framerate: "",
		gop: "",
		reference_frame: "",
		audioCodec: "",
		audioBitrate: "",
		sampleRate: "",
	});
	const [variantsErrors, setVariantsErrors] = useState({
		videoCodec: false,
		resolution: false,
		videoBitrate: false,
		profile: false,
		level: false,
		framerate: false,
		gop: false,
		reference_frame: false,
		audioCodec: false,
		audioBitrate: false,
		sampleRate: false,
	});
	const [variantsTableData, setVariantsTableData] = useState([]);
	const [editableVariantsRow, setEditableVariantsRow] = useState(null);
	const [editableVariantsRowIndex, setEditableVariantsRowIndex] = useState(null);
	const [playlistInputData, setPlaylistInputData] = useState({
		outputDir: "",
		inputFile: "",
		master_filename: "",
		hls_segment_size: "",
		hls_list_size: "",
		hls_playlist_type: "",
		hls_flags: "",
		preset: "",
	});
	const [playlistErrors, setPlaylistErrors] = useState({
		outputDir: false,
		inputFile: false,
		master_filename: false,
		hls_segment_size: false,
		hls_list_size: false,
		hls_playlist_type: false,
		hls_flags: false,
		preset: false,
	});
	const [snackbarStatus, setSnackbarStatus] = useState(false);
	const [snackbarData, setSnackbarData] = useState("");
	const [snackbarSeverity, setSnackbarSeverity] = useState("");
	const [templateValue, setTemplateValue] = useState("");
	const avc4k = [
		{
			"resolution": "1280x720",
			"videoCodec": "libx264",
			"videoBitrate": "3000000",
			"framerate": "30",
			"gop": "90",
			"reference_frame": "4",
			"profile": "main",
			"level": "4.1",
			"audioCodec": "aac",
			"audioBitrate": "128000",
			"sampleRate": "48000"
		}, 
		{
			"resolution": "1920x1080",
			"videoCodec": "libx264",
			"videoBitrate": "5000000",
			"framerate": "30",
			"gop": "90",
			"reference_frame": "4",
			"profile": "main",
			"level": "4.1",
			"audioCodec": "aac",
			"audioBitrate": "128000",
			"sampleRate": "48000"
		},
		{
			"resolution": "2560x1440",
			"videoCodec": "libx264",
			"videoBitrate": "8000000",
			"framerate": "30",
			"gop": "90",
			"reference_frame": "4",
			"profile": "main",
			"level": "4.1",
			"audioCodec": "aac",
			"audioBitrate": "192000",
			"sampleRate": "48000"
		},
		{
			"resolution": "3840x2160",
			"videoCodec": "libx264",
			"videoBitrate": "12000000",
			"framerate": "30",
			"gop": "90",
			"reference_frame": "4",
			"profile": "main",
			"level": "4.1",
			"audioCodec": "aac",
			"audioBitrate": "192000",
			"sampleRate": "48000"
		}
	];
	const hevc4k = [
        {
            "resolution": "1280x720",
            "videoCodec": "libx265",
            "videoBitrate": "3000000",
            "framerate": "30",
            "gop": "90",
            "reference_frame": "4",
            "profile": "main",
            "level": "4.1",
            "audioCodec": "aac",
            "audioBitrate": "128000", 
            "sampleRate": "48000"
        },
        {
            "resolution": "1920x1080",
            "videoCodec": "libx265",
            "videoBitrate": "5000000",
            "framerate": "30",
            "gop": "90",
            "reference_frame": "4",
            "profile": "main",
            "level": "4.1",
            "audioCodec": "aac",
            "audioBitrate": "128000",
            "sampleRate": "48000"
        },
        {
            "resolution": "2560x1440",
            "videoCodec": "libx265",
            "videoBitrate": "8000000",
            "framerate": "30",
            "gop": "90",
            "reference_frame": "4",
            "profile": "main",
            "level": "4.1",
            "audioCodec": "aac",
            "audioBitrate": "192000",
            "sampleRate": "48000"
        },
		{
            "resolution": "3840x2160",
            "videoCodec": "libx265",
            "videoBitrate": "12000000",
            "framerate": "30",
            "gop": "90",
            "reference_frame": "4",
            "profile": "main",
            "level": "4.1",
            "audioCodec": "aac",
            "audioBitrate": "192000",
            "sampleRate": "48000"
        }
    ];
	const avcFhd = [
        {
            "resolution": "640x360",
            "videoCodec": "libx264",
            "videoBitrate": "700000",
            "framerate": "25",
            "gop": "60",
            "reference_frame": "4",
            "profile": "main",
            "level": "4.1",
            "audioCodec": "aac",
            "audioBitrate": "128000", 
            "sampleRate": "48000"
        },
        {
            "resolution": "960x540",
            "videoCodec": "libx264",
            "videoBitrate": "1000000",
            "framerate": "25",
            "gop": "60",
            "reference_frame": "4",
            "profile": "main",
            "level": "4.1",
            "audioCodec": "aac",
            "audioBitrate": "128000",
            "sampleRate": "48000"
        },
        {
            "resolution": "1280x720",
            "videoCodec": "libx264",
            "videoBitrate": "2000000",
            "framerate": "25",
            "gop": "60",
            "reference_frame": "4",
            "profile": "main",
            "level": "4.1",
            "audioCodec": "aac",
            "audioBitrate": "128000",
            "sampleRate": "48000"
        },
		{
            "resolution": "1920x1080",
            "videoCodec": "libx264",
            "videoBitrate": "4000000",
            "framerate": "25",
            "gop": "60",
            "reference_frame": "4",
            "profile": "main",
            "level": "4.1",
            "audioCodec": "aac",
            "audioBitrate": "128000",
            "sampleRate": "48000"
        }
    ];
	const hevcFhd = [
        {
            "resolution": "640x360",
            "videoCodec": "libx265",
            "videoBitrate": "400000",
            "framerate": "25",
            "gop": "60",
            "reference_frame": "4",
            "profile": "main",
            "level": "4.1",
            "audioCodec": "aac",
            "audioBitrate": "128000", 
            "sampleRate": "48000"
        },
        {
            "resolution": "960x540",
            "videoCodec": "libx265",
            "videoBitrate": "700000",
            "framerate": "25",
            "gop": "60",
            "reference_frame": "4",
            "profile": "main",
            "level": "4.1",
            "audioCodec": "aac",
            "audioBitrate": "128000",
            "sampleRate": "48000"
        },
        {
            "resolution": "1280x720",
            "videoCodec": "libx265",
            "videoBitrate": "1500000",
            "framerate": "25",
            "gop": "60",
            "reference_frame": "4",
            "profile": "main",
            "level": "4.1",
            "audioCodec": "aac",
            "audioBitrate": "128000",
            "sampleRate": "48000"
        },
		{
            "resolution": "1920x1080",
            "videoCodec": "libx265",
            "videoBitrate": "3000000",
            "framerate": "25",
            "gop": "60",
            "reference_frame": "4",
            "profile": "main",
            "level": "4.1",
            "audioCodec": "aac",
            "audioBitrate": "128000",
            "sampleRate": "48000"
        }
    ]
	const hd = [
        {
            "resolution": "640x360",
            "videoCodec": "libx264",
            "videoBitrate": "700000",
            "framerate": "25",
            "gop": "60",
            "reference_frame": "4",
            "profile": "main",
            "level": "4.1",
            "audioCodec": "aac",
            "audioBitrate": "128000", 
            "sampleRate": "48000"
        },
        {
            "resolution": "960x540",
            "videoCodec": "libx264",
            "videoBitrate": "1000000",
            "framerate": "25",
            "gop": "60",
            "reference_frame": "4",
            "profile": "main",
            "level": "4.1",
            "audioCodec": "aac",
            "audioBitrate": "128000",
            "sampleRate": "48000"
        },
        {
            "resolution": "1280x720",
            "videoCodec": "libx264",
            "videoBitrate": "2000000",
            "framerate": "25",
            "gop": "60",
            "reference_frame": "4",
            "profile": "main",
            "level": "4.1",
            "audioCodec": "aac",
            "audioBitrate": "128000",
            "sampleRate": "48000"
        }
    ];
	const sd =  [
			{
				"resolution": "640x360",
				"videoCodec": "libx264",
				"videoBitrate": "700000",
				"framerate": "25",
				"gop": "60",
				"reference_frame": "4",
				"profile": "main",
				"level": "4.1",
				"audioCodec": "aac",
				"audioBitrate": "128000", 
				"sampleRate": "48000"
			},
			{
				"resolution": "960x540",
				"videoCodec": "libx264",
				"videoBitrate": "1000000",
				"framerate": "25",
				"gop": "60",
				"reference_frame": "4",
				"profile": "main",
				"level": "4.1",
				"audioCodec": "aac",
				"audioBitrate": "128000",
				"sampleRate": "48000"
			},
	];

	const templateDropdownData = [
		{ label: "4K (AVC)", value: "4K (AVC)" },
		{ label: "4K (HEVC)", value: "4K (HEVC)" },
		{ label: "FHD (AVC)", value: "FHD (AVC)" },
		{ label: "FHD (HEVC)", value: "FHD (HEVC)" },
		{ label: "HD", value: "HD" },
		{ label: "SD", value: "SD" },
	];

	const videoCodecDropdownData = [
		{ label: "H.264 (AVC)", value: "libx264" },
		{ label: "H.265 (HEVC)", value: "libx265" },
		{ label: "AV1", value: "libaom-av1" },
	];

	const resolutionDropdownData = [
		{ label: "360p (SD)", value: "640x360" },
		{ label: "540p (qHD)", value: "960x540" },
		{ label: "720p (HD)", value: "1280x720" },
		{ label: "1080p (FHD)", value: "1920x1080" },
		{ label: "1440p (QHD)", value: "2560x1440" },
		{ label: "2160p (4K)", value: "3840x2160" },
	];

	const pixfmtDropdownData = [{ label: "yuv420p", value: "yuv420p" }];

	const refrenceFrameDropdownData = [
		{ label: "3", value: "3" },
		{ label: "4", value: "4" },
	];

	const profileDropdownData = [
		{ label: "Baseline", value: "baseline" },
		{ label: "Main", value: "main" },
		{ label: "High", value: "high" },
	];

	const levelDropdownData = [
		{ label: "3.0", value: "3.0" },
		{ label: "3.1", value: "3.1" },
		{ label: "3.2", value: "3.2" },
		{ label: "4.0", value: "4.0" },
		{ label: "5.1", value: "5.1" },
		{ label: "5.2", value: "5.2" },
	];

	const fpsDropdownData = [
		{ label: "24", value: "24" },
		{ label: "25", value: "25" },
		{ label: "30", value: "30" },
		{ label: "59.940", value: "59.940" },
	];

	const gopDropdownData = [
		{ label: "60", value: "60" },
		{ label: "90", value: "90" },
	];

	const audioCodecDropdownData = [
		{ label: "Advanced Audio Coding (aac)", value: "aac" },
		{ label: "MPEG-1 AL-2 (mp2)", value: "mp2" },
		{ label: "Dolby Digital (ac3)", value: "ac3" },
	];

	const bitrateDropdownData = [
		{ label: "112000", value: "112000" },
		{ label: "128000", value: "128000" },
		{ label: "192000", value: "192000" },
		{ label: "224000", value: "224000" },
		{ label: "256000", value: "256000" },
	];

	const sampleRateDropdownData = [
		{ label: "32000", value: "32000" },
		{ label: "44100", value: "44100" },
		{ label: "48000", value: "48000" },
	];

	const flagsDropdownData = [
		{ label: "delete_segments", value: "delete_segments" },
		{ label: "append_list", value: "append_list" },
		{ label: "single_file", value: "single_file" },
	];

	const presetsDropdownData = [
		{ label: "Slow", value: "slow" },
		{ label: "Medium", value: "medium" },
		{ label: "Fast", value: "fast" },
	];

	const playlistTypeDropdownData = [
		{ label: "LIVE", value: "live" },
		{ label: "VOD", value: "vod" },
	];

	const StyledTableRow = styled(TableRow)(({ theme, index }) => ({
		backgroundColor: editableVariantsRowIndex === index ? "#ffffcc" : "inherit",
	}));

	const StyledTableCell = styled(TableCell)(({ theme }) => ({
		[`&.${tableCellClasses.head}`]: {
			backgroundColor: "#9289F2",
			color: theme.palette.common.white,
		},
		[`&.${tableCellClasses.body}`]: {
			fontSize: 14,
		},
	}));

	const handleVariantsInputData = (e) => {
		setVariantsInputData({ ...variantsInputData, [e.target.name]: e.target.value });
		setVariantsErrors({ ...variantsErrors, [e.target.name]: e.target.value === "" ? true : false });
	};

	const handleClearVariantsInput = (name) => {
		setVariantsInputData({ ...variantsInputData, [name]: "" });
		setVariantsErrors({ ...variantsErrors, [name]: true });
	};

	const handleClearAllVariantsInput = () => {
		setVariantsInputData({ ...variantsInputData, videoCodec: "", resolution: "", videoBitrate: "", profile: "", level: "", framerate: "", gop: "", reference_frame: "", audioCodec: "", audioBitrate: "", sampleRate: "" });
		setVariantsErrors({ ...variantsErrors, videoCodec: false, resolution: false, videoBitrate: false, profile: false, level: false, framerate: false, gop: false, reference_frame: false,  audioCodec: false, audioBitrate: false, sampleRate: false });
	};

	const handleSaveVariants = () => {
		let newErrors = {};
		Object.keys(variantsInputData).forEach((key) => {
			newErrors[key] = variantsInputData[key] === "";
		});
		console.log("newErrors::", newErrors);
		setVariantsErrors(newErrors);
		let isAnyFieldTrue = Object.values(newErrors).some((value) => value === true);
		console.log("isAnyFieldTrue::", isAnyFieldTrue);
		if (!isAnyFieldTrue) {
			let tempVariantsTableData = Array.from(variantsTableData);
			let tempVariantsInputData = cloneDeep(variantsInputData);
			if (tempVariantsInputData.hls_playlist_type === "vod") {
				delete tempVariantsInputData.hls_flags;
			} else {
				delete tempVariantsInputData.hls_playlist_type;
			}
			console.log("handleSaveVariants::tempVariantsInputData::", tempVariantsInputData);
			tempVariantsTableData.push(tempVariantsInputData);
			setVariantsTableData(Array.from(tempVariantsTableData));
			console.log("setVariantsTableData::", Array.from(tempVariantsTableData));
			handleClearAllVariantsInput();
		}
	};

	const handleDeleteVariantsRow = (postIndex) => {
		setVariantsTableData((prevData) => prevData.filter((_, prevIndex) => prevIndex !== postIndex));
	};

	const handleEditVariantsRow = (index) => {
		setEditableVariantsRow(variantsTableData[index]);
		setEditableVariantsRowIndex(index);
	};

	const handlePlaylistInputData = (e) => {
		console.log("handlePlaylistInputData::",e.target.name," ",e.target.value)
		setPlaylistInputData({ ...playlistInputData, [e.target.name]: e.target.value });
		setPlaylistErrors({ ...playlistErrors, [e.target.name]: e.target.value === "" ? true : false });
	};

	const handleClearPlaylistInput = (name) => {
		setPlaylistInputData({ ...playlistInputData, [name]: "" });
		setPlaylistErrors({ ...playlistErrors, [name]: true });
	};

	function transformResolution(json) {
		// Parse the JSON string if it's a string, otherwise use the object directly
		const data = typeof json === 'string' ? JSON.parse(json) : json;
	
		// Process each variant in the array
		data.variants.forEach(variant => {
			const [width, height] = variant.resolution.split('x');
	
			// Add new keys with string values
			variant.width = width;
			variant.height = height;
	
			// Remove the original resolution key
			delete variant.resolution;
		});
	
		// Return the transformed data
		return data;
	}

	function saveToSessionStorage(data) {
		let existingData = sessionStorage.getItem('transcodingSessions');
		let sessions = existingData ? JSON.parse(existingData) : [];
		const { playback_url, process_id, message } = data;
	    const channelName = playback_url.split('/')[3];
		const status = message.toLowerCase().includes('started') ? 'started' : 'stopped';
		const newSession = {
			playback_url,
			process_id,
			channelName,
			status
		};
		sessions.push(newSession);
		sessionStorage.setItem('transcodingSessions', JSON.stringify(sessions));
		console.log('Data saved to sessionStorage:', newSession);
	}
	

	const handleSubmitJob = () => {
		let newErrors = {};
		Object.keys(playlistInputData).forEach((key) => {
			newErrors[key] = playlistInputData[key] === "";
		});
		console.log("newErrors::", newErrors);
		setPlaylistErrors(newErrors);
		let isAnyFieldTrue = Object.values(newErrors).some((value) => value === true);
		console.log("isAnyFieldTrue::", isAnyFieldTrue);
		if (isAnyFieldTrue) {
			setSnackbarStatus(true);
			setSnackbarData("Please fill all required fields");
			setSnackbarSeverity("error");
			setTimeout(() => {
				setSnackbarStatus(false);
				setSnackbarData("");
				setSnackbarSeverity("");
			}, 2000);
		} else if (variantsTableData.length === 0) {
			let newErrors = {};
			Object.keys(variantsInputData).forEach((key) => {
				newErrors[key] = variantsInputData[key] === "";
			});
			console.log("newErrors::", newErrors);
			setVariantsErrors(newErrors);
			setSnackbarStatus(true);
			setSnackbarData("Please fill and save Profile Variants Data");
			setSnackbarSeverity("error");
			setTimeout(() => {
				setSnackbarStatus(false);
				setSnackbarData("");
				setSnackbarSeverity("");
			}, 2000);
		} else {
			let body = {
				inputFile: playlistInputData.inputFile,
				outputDir: playlistInputData.outputDir,
				variants: variantsTableData,
				master_filename: playlistInputData.master_filename,
				hls_segment_size: playlistInputData.hls_segment_size,
				preset: playlistInputData.preset,
				hls_list_size: playlistInputData.hls_playlist_type === "vod" ? "" : playlistInputData.hls_list_size,
				hls_flags: playlistInputData.hls_playlist_type === "vod" ? "" : playlistInputData.hls_flags,
				hls_playlist_type: playlistInputData.hls_playlist_type === "live" ? "" : playlistInputData.hls_playlist_type,
			};
			const transformedJson = transformResolution(body);
			console.log("handleSubmitJob::transformedJson::", transformedJson);
			let url = environment.baseURL + environment.newModuleAPIs.common.prefix + environment.newModuleAPIs.transcoder.submitRequest.POST;
			console.log("handleSubmitJob::url::", url);
			globalService.postData(url, transformedJson).then((res) => {
				console.log("res :: ", res);
				if (res?.message.includes("successfully")) {
					saveToSessionStorage(res);
					handleCancelJob();
					setSnackbarStatus(true);
					setSnackbarData(res?.message);
					setSnackbarSeverity("info");
					setTimeout(() => {
						setSnackbarStatus(false);
						setSnackbarData("");
						setSnackbarSeverity("");
					}, 2000);
				} else {
					setSnackbarStatus(true);
					setSnackbarData(res?.Error);
					setSnackbarSeverity("error");
					setTimeout(() => {
						setSnackbarStatus(false);
						setSnackbarData("");
						setSnackbarSeverity("");
					}, 2000);
				}
			});
		}
	};

	const handleCancelJob = () => {
		setVariantsInputData({ ...variantsInputData, videoCodec: "", resolution: "", videoBitrate: "", profile: "", level: "", framerate: "", gop: "", reference_frame: "",  audioCodec: "", audioBitrate: "", sampleRate: ""});
		setVariantsErrors({ ...variantsErrors, videoCodec: false, resolution: false, videoBitrate: false, profile: false, level: false, framerate: false, gop: false, reference_frame: false,  audioCodec: false, audioBitrate: false, sampleRate: false });
		setVariantsTableData([]);
		setPlaylistInputData({ ...playlistInputData, outputDir: "", inputFile: "", master_filename: "", hls_segment_size: "", hls_list_size: "", hls_playlist_type: "", hls_flags: "", preset: "" });
		setPlaylistErrors({ ...playlistErrors, outputDir: false, inputFile: false, master_filename: false, hls_segment_size: false, hls_list_size: false, hls_playlist_type: false, hls_flags: false, preset: false });
	};

	useEffect(() => {
		console.log("variantsInputData::", variantsInputData);
		return () => {};
	}, [variantsInputData]);

	useEffect(() => {
		console.log("variantsTableData::", variantsTableData);
		return () => {};
	}, [variantsTableData]);

	useEffect(() => {
		console.log("templateValue::", templateValue);
		if(templateValue === "4K (AVC)"){
			setVariantsTableData(avc4k)
		} else if(templateValue === "4K (HEVC)"){
			setVariantsTableData(hevc4k)
		} else if(templateValue === "FHD (AVC)"){
			setVariantsTableData(avcFhd)
		} else if(templateValue === "FHD (HEVC)"){
			setVariantsTableData(hevcFhd)
		} else if(templateValue === "HD"){
			setVariantsTableData(hd)
		} else if(templateValue === "SD"){
			setVariantsTableData(sd)
		}
		return () => {};
	}, [templateValue]);

	return (
		<>
			<Card sx={{ p: 3, mb: 3 }}>
				<Box component="section" sx={{ p: 3, mb: 3 }}>
					<Grid container spacing={2}>
						<Grid item xs={3}>
							<FormLabel component="legend" size="small">
								Event Name
								<span style={{ color: "red" }}>*</span>
							</FormLabel>
							<FormControl size="small" error={playlistErrors.outputDir}>
								<Box display="flex" alignItems="flex-start">
									<TextField sx={{ minWidth: 250 }} name="outputDir" color="secondary" size="small" value={playlistInputData.outputDir} onChange={(e) => handlePlaylistInputData(e)} error={playlistErrors.outputDir} helperText={playlistErrors.outputDir && "Please enter an event name."} />
									{playlistInputData.outputDir && (
										<IconButton onClick={() => handleClearPlaylistInput("outputDir")}>
											<ClearIcon />
										</IconButton>
									)}
								</Box>
							</FormControl>
						</Grid>
					</Grid>
				</Box>
			</Card>
			<Card sx={{ p: 3, mb: 3 }}>
				<Grid container spacing={2}>
					<Grid item xs={12}>
						<Typography variant="h4" color="secondary">
							1. Input
						</Typography>
					</Grid>
				</Grid>
				<Box component="section" sx={{ p: 3, mb: 3 }}>
					<Grid container spacing={4} sx={{ pt: 3 }}>
						<Grid item xs={6}>
							<FormLabel component="legend" size="small">
								URL
								<span style={{ color: "red" }}>*</span>
							</FormLabel>
							<FormControl size="small" error={playlistErrors.inputFile}>
								<Box display="flex" alignItems="flex-start">
									<TextField sx={{ minWidth: 500 }} name="inputFile" color="secondary" size="small" placeholder=".m3u8 or .mp4" value={playlistInputData.inputFile} onChange={(e) => handlePlaylistInputData(e)} error={playlistErrors.inputFile} helperText={playlistErrors.inputFile && "Please enter a url."} />
									{playlistInputData.inputFile && (
										<IconButton onClick={() => handleClearPlaylistInput("inputFile")}>
											<ClearIcon />
										</IconButton>
									)}
								</Box>
							</FormControl>
						</Grid>
					</Grid>
				</Box>
				<Grid container spacing={2}>
					<Grid item xs={12}>
						<Typography variant="h4" color="secondary">
							2. Profile
						</Typography>
					</Grid>
				</Grid>
				<Box component="section" sx={{ p: 3, mb: 3 }}>
					<Grid container spacing={4} sx={{ pt: 1 }}>
						<Grid item xs={6}>
							<FormLabel component="legend" size="small">
								Template
							</FormLabel>
							<FormControl size="small" >
								<Box display="flex" alignItems="center">
										<Select sx={{ minWidth: 250 }} name="template" color="secondary" value={templateValue} onChange={(e) => setTemplateValue(e.target.value)}>
											{templateDropdownData.map((each, index) => (
												<MenuItem value={each.value} key={"template_" + index}>
													{each.label}
												</MenuItem>
											))}
										</Select>
										{templateValue && (
											<IconButton
												onClick={() => {
													setTemplateValue("");
													setVariantsTableData([]); 
												}}
											>
												<ClearIcon />
											</IconButton>
										)}
								</Box>
							</FormControl>
						</Grid>
					</Grid>
				</Box>
				{variantsTableData && variantsTableData.length > 0 && (
					<Box component="section" sx={{ p: 3 }}>
						<TableContainer component={Paper}>
							<Table sx={{ minWidth: 700 }}>
								<TableHead>
									<TableRow>
										<StyledTableCell align="left">Video Codec</StyledTableCell>
										<StyledTableCell align="left">Resolution</StyledTableCell>
										<StyledTableCell align="left">Reference Frame</StyledTableCell>
										<StyledTableCell align="left">Video Bitrate</StyledTableCell>
										<StyledTableCell align="left">Profile</StyledTableCell>
										<StyledTableCell align="left">Level</StyledTableCell>
										<StyledTableCell align="left">FPS</StyledTableCell>
										<StyledTableCell align="left">GOP</StyledTableCell>
										<StyledTableCell align="left">Audio Codec</StyledTableCell>
										<StyledTableCell align="left">Audio Bitrate(bps)</StyledTableCell>
										<StyledTableCell align="left">Sample rate</StyledTableCell>
										<StyledTableCell align="left">Actions</StyledTableCell>
									</TableRow>
								</TableHead>
								<TableBody>
									{variantsTableData.map((row, index) => (
										<StyledTableRow key={index} index={index}>
											<StyledTableCell align="left">{row.videoCodec}</StyledTableCell>
											<StyledTableCell align="left">{row.resolution}</StyledTableCell>
											<StyledTableCell align="left">{row.reference_frame}</StyledTableCell>
											<StyledTableCell align="left">{row.videoBitrate}</StyledTableCell>
											<StyledTableCell align="left">{row.profile}</StyledTableCell>
											<StyledTableCell align="left">{row.level}</StyledTableCell>
											<StyledTableCell align="left">{row.framerate}</StyledTableCell>
											<StyledTableCell align="left">{row.gop}</StyledTableCell>
											<StyledTableCell align="left">{row.audioCodec}</StyledTableCell>
											<StyledTableCell align="left">{row.audioBitrate}</StyledTableCell>
											<StyledTableCell align="left">{row.sampleRate}</StyledTableCell>
											<StyledTableCell align="left" style={{ display: "flex" }}>
												<Tooltip title="Delete">
													<IconButton onClick={() => handleDeleteVariantsRow(index)}>
														<DeleteForeverIcon sx={{ mr: 1 }} style={{ color: "white", backgroundImage: "linear-gradient(to right, purple , #8A2BE2)", borderRadius: 20 }} />
													</IconButton>
												</Tooltip>
											</StyledTableCell>
										</StyledTableRow>
									))}
								</TableBody>
							</Table>
						</TableContainer>
					</Box>
				)}
				<form noValidate>
					<Box component="section" sx={{ p: 3, mb: 3 }}>
						<Alert variant="filled" sx={{ bgcolor: "#9289F2", color: "#FFFFFF" }}>
							Video
						</Alert>
						<Divider />
						<Grid container spacing={4} sx={{ pt: 3 }}>
							<Grid item xs={3}>
								<FormLabel component="legend" size="small">
									Video Codec
									<span style={{ color: "red" }}>*</span>
								</FormLabel>
								<FormControl size="small" error={variantsErrors.videoCodec}>
									<Box display="flex" alignItems="center">
										<Select sx={{ minWidth: 250 }} name="videoCodec" color="secondary" value={editableVariantsRow ? editableVariantsRow.videoCodec : variantsInputData.videoCodec} onChange={(e) => handleVariantsInputData(e)}>
											{videoCodecDropdownData.map((each, index) => (
												<MenuItem value={each.value} key={"video_codec_" + index}>
													{each.label}
												</MenuItem>
											))}
										</Select>
										{variantsInputData.videoCodec && (
											<IconButton onClick={() => handleClearVariantsInput("videoCodec")}>
												<ClearIcon />
											</IconButton>
										)}
									</Box>
									<FormHelperText>{variantsErrors.videoCodec && "Please select a video codec."}</FormHelperText>
								</FormControl>
							</Grid>
							<Grid item xs={3}>
								<FormLabel component="legend" size="small">
									Resolution
									<span style={{ color: "red" }}>*</span>
								</FormLabel>
								<FormControl size="small" error={variantsErrors.resolution}>
									<Box display="flex" alignItems="center">
										<Select sx={{ minWidth: 250 }} name="resolution" color="secondary" value={editableVariantsRow ? editableVariantsRow.resolution : variantsInputData.resolution} onChange={(e) => handleVariantsInputData(e)}>
											{resolutionDropdownData.map((each, index) => (
												<MenuItem value={each.value} key={"video_codec_" + index}>
													{each.label}
												</MenuItem>
											))}
										</Select>
										{variantsInputData.resolution && (
											<IconButton onClick={() => handleClearVariantsInput("resolution")}>
												<ClearIcon />
											</IconButton>
										)}
									</Box>
									<FormHelperText>{variantsErrors.resolution && "Please select a resolution."}</FormHelperText>
								</FormControl>
							</Grid>
							<Grid item xs={3}>
								<FormLabel component="legend" size="small">
									Reference Frame
									<span style={{ color: "red" }}>*</span>
								</FormLabel><FormControl size="small" error={variantsErrors.reference_frame}>
									<Box display="flex" alignItems="center">
										<Select sx={{ minWidth: 250 }} name="reference_frame" color="secondary" value={editableVariantsRow ? editableVariantsRow.reference_frame : variantsInputData.reference_frame} onChange={(e) => handleVariantsInputData(e)}>
											{refrenceFrameDropdownData.map((each, index) => {
												return (
													<MenuItem value={each.value} key={"reference_frame_" + index}>
														{each.label}
													</MenuItem>
												);
											})}
										</Select>
										{variantsInputData.reference_frame && (
											<IconButton onClick={() => handleClearVariantsInput("reference_frame")}>
												<ClearIcon />
											</IconButton>
										)}
									</Box>
									<FormHelperText>{variantsErrors.reference_frame && "Please select a reference_frame."}</FormHelperText>
								</FormControl>
							</Grid>
						</Grid>
						<Grid container spacing={4} sx={{ pt: 3 }}>
							<Grid item xs={3}>
								<FormLabel component="legend" size="small">
									Video Bitrate(bps)
									<span style={{ color: "red" }}>*</span>
								</FormLabel>
								<FormControl size="small" error={variantsErrors.videoBitrate}>
									<Box display="flex" alignItems="flex-start">
										<TextField sx={{ minWidth: 250 }} name="videoBitrate" color="secondary" size="small" value={editableVariantsRow ? editableVariantsRow.videoBitrate : variantsInputData.videoBitrate} onChange={(e) => handleVariantsInputData(e)} error={variantsErrors.videoBitrate} helperText={variantsErrors.videoBitrate && "Please enter a video bitrate."} />
										{variantsInputData.videoBitrate && (
											<IconButton onClick={() => handleClearVariantsInput("videoBitrate")}>
												<ClearIcon />
											</IconButton>
										)}
									</Box>
								</FormControl>
							</Grid>
							<Grid item xs={3}>
								<FormLabel component="legend" size="small">
									Profile
									<span style={{ color: "red" }}>*</span>
								</FormLabel>
								<FormControl size="small" error={variantsErrors.profile}>
									<Box display="flex" alignItems="center">
										<Select sx={{ minWidth: 250 }} name="profile" color="secondary" value={editableVariantsRow ? editableVariantsRow.profile : variantsInputData.profile} onChange={(e) => handleVariantsInputData(e)}>
											{profileDropdownData.map((each, index) => {
												return (
													<MenuItem value={each.value} key={"profile_" + index}>
														{each.label}
													</MenuItem>
												);
											})}
										</Select>
										{variantsInputData.profile && (
											<IconButton onClick={() => handleClearVariantsInput("profile")}>
												<ClearIcon />
											</IconButton>
										)}
									</Box>
									<FormHelperText>{variantsErrors.profile && "Please select a profile."}</FormHelperText>
								</FormControl>
							</Grid>
							<Grid item xs={3}>
								<FormLabel component="legend" size="small">
									Level
									<span style={{ color: "red" }}>*</span>
								</FormLabel>
								<FormControl size="small" error={variantsErrors.level}>
									<Box display="flex" alignItems="center">
										<Select sx={{ minWidth: 250 }} name="level" color="secondary" value={editableVariantsRow ? editableVariantsRow.level : variantsInputData.level} onChange={(e) => handleVariantsInputData(e)}>
											{levelDropdownData.map((each, index) => {
												return (
													<MenuItem value={each.value} key={"level_" + index}>
														{each.label}
													</MenuItem>
												);
											})}
										</Select>
										{variantsInputData.level && (
											<IconButton onClick={() => handleClearVariantsInput("level")}>
												<ClearIcon />
											</IconButton>
										)}
									</Box>
									<FormHelperText>{variantsErrors.level && "Please select a level."}</FormHelperText>
								</FormControl>
							</Grid>
							<Grid item xs={3}>
								<FormLabel component="legend" size="small">
									FPS
									<span style={{ color: "red" }}>*</span>
								</FormLabel>
								{/* <FormControl size="small" error={variantsErrors.framerate}>
									<Box display="flex" alignItems="flex-start">
										<TextField sx={{ minWidth: 250 }} name="framerate" color="secondary" size="small" value={editableVariantsRow ? editableVariantsRow.framerate : variantsInputData.framerate} onChange={(e) => handleVariantsInputData(e)} error={variantsErrors.framerate} helperText={variantsErrors.framerate && "Please enter a framerate."} />
										{variantsInputData.framerate && (
											<IconButton onClick={() => handleClearVariantsInput("framerate")}>
												<ClearIcon />
											</IconButton>
										)}
									</Box>
								</FormControl> */}
								<FormControl size="small" error={variantsErrors.framerate}>
									<Box display="flex" alignItems="center">
										<Select sx={{ minWidth: 250 }} name="framerate" color="secondary" value={editableVariantsRow ? editableVariantsRow.framerate : variantsInputData.framerate} onChange={(e) => handleVariantsInputData(e)}>
											{fpsDropdownData.map((each, index) => {
												return (
													<MenuItem value={each.value} key={"framerate_" + index}>
														{each.label}
													</MenuItem>
												);
											})}
										</Select>
										{variantsInputData.framerate && (
											<IconButton onClick={() => handleClearVariantsInput("framerate")}>
												<ClearIcon />
											</IconButton>
										)}
									</Box>
									<FormHelperText>{variantsErrors.framerate && "Please select a framerate."}</FormHelperText>
								</FormControl>
							</Grid>
						</Grid>
						<Grid container spacing={4} sx={{ pt: 3 }}>
							<Grid item xs={3}>
								<FormLabel component="legend" size="small">
									GOP
									<span style={{ color: "red" }}>*</span>
								</FormLabel>
								{/* <FormControl size="small" error={variantsErrors.gop}>
									<Box display="flex" alignItems="flex-start">
										<TextField sx={{ minWidth: 250 }} name="gop" color="secondary" size="small" value={editableVariantsRow ? editableVariantsRow.gop : variantsInputData.gop} onChange={(e) => handleVariantsInputData(e)} error={variantsErrors.gop} helperText={variantsErrors.gop && "Please enter a gop."} />
										{variantsInputData.gop && (
											<IconButton onClick={() => handleClearVariantsInput("gop")}>
												<ClearIcon />
											</IconButton>
										)}
									</Box>
								</FormControl> */}
								<FormControl size="small" error={variantsErrors.gop}>
									<Box display="flex" alignItems="center">
										<Select sx={{ minWidth: 250 }} name="gop" color="secondary" value={editableVariantsRow ? editableVariantsRow.gop : variantsInputData.gop} onChange={(e) => handleVariantsInputData(e)}>
											{gopDropdownData.map((each, index) => {
												return (
													<MenuItem value={each.value} key={"gop_" + index}>
														{each.label}
													</MenuItem>
												);
											})}
										</Select>
										{variantsInputData.gop && (
											<IconButton onClick={() => handleClearVariantsInput("gop")}>
												<ClearIcon />
											</IconButton>
										)}
									</Box>
									<FormHelperText>{variantsErrors.gop && "Please select a gop."}</FormHelperText>
								</FormControl>
							</Grid>
						</Grid>
					</Box>
					<Box component="section" sx={{ p: 3, mb: 3 }}>
						<Alert variant="filled" sx={{ bgcolor: "#9289F2", color: "#FFFFFF" }}>
							Audio
						</Alert>
						<Divider />
						<Grid container spacing={4} sx={{ pt: 3 }}>
							<Grid item xs={3}>
								<FormLabel component="legend" size="small">
									Audio Codec
									<span style={{ color: "red" }}>*</span>
								</FormLabel>
								<FormControl size="small" error={variantsErrors.audioCodec}>
									<Box display="flex" alignItems="center">
										<Select sx={{ minWidth: 250 }} name="audioCodec" color="secondary" value={editableVariantsRow ? editableVariantsRow.audioCodec : variantsInputData.audioCodec} onChange={(e) => handleVariantsInputData(e)}>
											{audioCodecDropdownData.map((each, index) => {
												return (
													<MenuItem value={each.value} key={"audio_codec_" + index}>
														{each.label}
													</MenuItem>
												);
											})}
										</Select>
										{variantsInputData.audioCodec && (
											<IconButton onClick={() => handleClearVariantsInput("audioCodec")}>
												<ClearIcon />
											</IconButton>
										)}
									</Box>
									<FormHelperText>{variantsErrors.audioCodec && "Please select an audio codec."}</FormHelperText>
								</FormControl>
							</Grid>
							<Grid item xs={3}>
								<FormLabel component="legend" size="small">
									Bitrate(bps)
									<span style={{ color: "red" }}>*</span>
								</FormLabel>
								<FormControl size="small" error={variantsErrors.audioBitrate}>
									<Box display="flex" alignItems="center">
										<Select sx={{ minWidth: 250 }} name="audioBitrate" color="secondary" value={editableVariantsRow ? editableVariantsRow.audioBitrate : variantsInputData.audioBitrate} onChange={(e) => handleVariantsInputData(e)}>
											{bitrateDropdownData.map((each, index) => {
												return (
													<MenuItem value={each.value} key={"audio_bitrate_" + index}>
														{each.label}
													</MenuItem>
												);
											})}
										</Select>
										{variantsInputData.audioBitrate && (
											<IconButton onClick={() => handleClearVariantsInput("audioBitrate")}>
												<ClearIcon />
											</IconButton>
										)}
									</Box>
									<FormHelperText>{variantsErrors.audioBitrate && "Please select a bitrate."}</FormHelperText>
								</FormControl>
							</Grid>
							<Grid item xs={3}>
								<FormLabel component="legend" size="small">
									Sample rate
									<span style={{ color: "red" }}>*</span>
								</FormLabel>
								<FormControl size="small" error={variantsErrors.sampleRate}>
									<Box display="flex" alignItems="center">
										<Select sx={{ minWidth: 250 }} name="sampleRate" color="secondary" value={editableVariantsRow ? editableVariantsRow.sampleRate : variantsInputData.sampleRate} onChange={(e) => handleVariantsInputData(e)}>
											{sampleRateDropdownData.map((each, index) => (
												<MenuItem value={each.value} key={`sample_rate_${index}`}>
													{each.label}
												</MenuItem>
											))}
										</Select>
										{variantsInputData.sampleRate && (
											<IconButton onClick={() => handleClearVariantsInput("sampleRate")}>
												<ClearIcon />
											</IconButton>
										)}
									</Box>
									<FormHelperText>{variantsErrors.sampleRate && "Please select a sample rate."}</FormHelperText>
								</FormControl>
							</Grid>
						</Grid>
						<Grid container spacing={4} sx={{ pt: 3 }}>
								<Grid item xs={3}>
								</Grid>
								<Grid item xs={3}></Grid>
								<Grid item xs={3} style={{ marginTop: "20px" }}>
									<Button sx={{ color: "#9289f2", borderBlockColor: "#9289f2", minWidth: 250 }} size="medium" component="label" variant="outlined" startIcon={<ClearIcon />} onClick={() => handleClearAllVariantsInput()}>
										Clear
									</Button>
								</Grid>
								<Grid item xs={3} style={{ marginTop: "20px" }}>
									<Button sx={{ background: "#9289f2", minWidth: 250 }} size="medium" variant="contained" startIcon={<AddCircleIcon />} onClick={() => handleSaveVariants()}>
										{editableVariantsRow ? "Update" : "Save"}
									</Button>
								</Grid>
							</Grid>
					</Box>
					<Box component="section" sx={{ p: 3, mb: 3 }}>
						<Alert variant="filled" sx={{ bgcolor: "#9289F2", color: "#FFFFFF" }}>
							HLS Output
						</Alert>
						<Divider />
						<Grid container spacing={4} sx={{ pt: 3 }}>
							<Grid item xs={3}>
								<FormLabel component="legend" size="small">
									Segment Size
									<span style={{ color: "red" }}>*</span>
								</FormLabel>
								<FormControl size="small" error={playlistErrors.hls_segment_size}>
									<Box display="flex" alignItems="flex-start">
										<TextField sx={{ minWidth: 250 }} name="hls_segment_size" color="secondary" size="small" value={playlistInputData.hls_segment_size} onChange={(e) => handlePlaylistInputData(e)} error={playlistErrors.hls_segment_size} helperText={playlistErrors.hls_segment_size && "Please enter a segment size."} />
										{playlistInputData.hls_segment_size && (
											<IconButton onClick={() => handleClearPlaylistInput("hls_segment_size")}>
												<ClearIcon />
											</IconButton>
										)}
									</Box>
								</FormControl>
							</Grid>
							<Grid item xs={3}>
								<FormLabel component="legend" size="small">
									List Size
									<span style={{ color: "red" }}>*</span>
								</FormLabel>
								<FormControl size="small" error={playlistErrors.hls_list_size}>
									<Box display="flex" alignItems="flex-start">
										<TextField sx={{ minWidth: 250 }} name="hls_list_size" color="secondary" size="small" value={playlistInputData.hls_list_size} onChange={(e) => handlePlaylistInputData(e)} error={playlistErrors.hls_list_size} helperText={playlistErrors.hls_list_size && "Please enter a list size."} />
										{playlistInputData.hls_list_size && (
											<IconButton onClick={() => handleClearPlaylistInput("hls_list_size")}>
												<ClearIcon />
											</IconButton>
										)}
									</Box>
								</FormControl>
							</Grid>
							<Grid item xs={3}>
								<FormLabel component="legend" size="small">
									Playlist Type
									<span style={{ color: "red" }}>*</span>
								</FormLabel>
								<FormControl size="small" error={playlistErrors.hls_playlist_type}>
									<Box display="flex" alignItems="center">
										<Select sx={{ minWidth: 250 }} name="hls_playlist_type" color="secondary" value={playlistInputData.hls_playlist_type} onChange={(e) => handlePlaylistInputData(e)}>
											{playlistTypeDropdownData.map((each, index) => {
												return (
													<MenuItem value={each.value} key={"hls_playlist_type" + index}>
														{each.label}
													</MenuItem>
												);
											})}
										</Select>
										{playlistInputData.hls_playlist_type && (
											<IconButton onClick={() => handleClearPlaylistInput("hls_playlist_type")}>
												<ClearIcon />
											</IconButton>
										)}
									</Box>
									<FormHelperText>{playlistErrors.hls_playlist_type && "Please select a playlist type."}</FormHelperText>
								</FormControl>
							</Grid>
							<Grid item xs={3}>
								<FormLabel component="legend" size="small">
									Flags
									<span style={{ color: "red" }}>*</span>
								</FormLabel>
								<FormControl size="small" error={playlistErrors.hls_flags}>
									<Box display="flex" alignItems="center">
										<Select sx={{ minWidth: 250 }} name="hls_flags" color="secondary" value={playlistInputData.hls_flags} onChange={(e) => handlePlaylistInputData(e)}>
											{flagsDropdownData.map((each, index) => (
												<MenuItem value={each.value} key={`hls_flags_${index}`}>
													{each.label}
												</MenuItem>
											))}
										</Select>
										{playlistInputData.hls_flags && (
											<IconButton onClick={() => handleClearPlaylistInput("hls_flags")}>
												<ClearIcon />
											</IconButton>
										)}
									</Box>
									<FormHelperText>{playlistErrors.hls_flags && "Please select flags."}</FormHelperText>
								</FormControl>
							</Grid>
						</Grid>
						<Grid container spacing={4} sx={{ pt: 3 }}>
							<Grid item xs={3}>
								<FormLabel component="legend" size="small">
									Preset
									<span style={{ color: "red" }}>*</span>
								</FormLabel>
								<FormControl size="small" error={playlistErrors.preset}>
									<Box display="flex" alignItems="center">
										<Select sx={{ minWidth: 250 }} name="preset" color="secondary" value={playlistInputData.preset} onChange={(e) => handlePlaylistInputData(e)}>
											{presetsDropdownData.map((each, index) => (
												<MenuItem value={each.value} key={`preset_${index}`}>
													{each.label}
												</MenuItem>
											))}
										</Select>
										{playlistInputData.preset && (
											<IconButton onClick={() => handleClearPlaylistInput("preset")}>
												<ClearIcon />
											</IconButton>
										)}
									</Box>
									<FormHelperText>{playlistErrors.preset && "Please select preset."}</FormHelperText>
								</FormControl>
							</Grid>
						</Grid>
					</Box>
				</form>
				<Grid container spacing={2}>
					<Grid item xs={12}>
						<Typography variant="h4" color="secondary">
							3. Output
						</Typography>
					</Grid>
				</Grid>
				<Box component="section" sx={{ p: 3, mb: 3 }}>
					<Grid container spacing={4} sx={{ pt: 3 }}>
						<Grid item xs={3}>
							<FormLabel component="legend" size="small">
								Master Filename
								<span style={{ color: "red" }}>*</span>
							</FormLabel>
							<FormControl size="small" error={playlistErrors.master_filename}>
								<Box display="flex" alignItems="flex-start">
									<TextField sx={{ minWidth: 250 }} name="master_filename" color="secondary" size="small" value={playlistInputData.master_filename} onChange={(e) => handlePlaylistInputData(e)} error={playlistErrors.master_filename} helperText={playlistErrors.master_filename && "Please enter a master playlist path."} />
									{playlistInputData.master_filename && (
										<IconButton onClick={() => handleClearPlaylistInput("master_filename")}>
											<ClearIcon />
										</IconButton>
									)}
								</Box>
							</FormControl>
						</Grid>
						<Grid item xs={3}></Grid>
						<Grid item xs={3} style={{ marginTop: "20px" }}>
							<Button
								sx={{ color: "#9289f2", borderBlockColor: "#9289f2", minWidth: 250 }}
								size="medium"
								component="label"
								variant="outlined"
								startIcon={<CancelIcon />}
								onClick={() => {
									handleCancelJob();
								}}
							>
								Cancel
							</Button>
						</Grid>
						<Grid item xs={3} style={{ marginTop: "20px" }}>
							<Button
								sx={{ background: "#9289f2", minWidth: 250 }}
								size="medium"
								component="label"
								variant="contained"
								startIcon={<PublishIcon />}
								onClick={() => {
									handleSubmitJob();
								}}
							>
								Submit & Start
							</Button>
						</Grid>
					</Grid>
				</Box>
			</Card>
			{snackbarStatus && <SnackbarClass status={snackbarStatus} data={snackbarData} severity={snackbarSeverity}></SnackbarClass>}
		</>
	);
        }
