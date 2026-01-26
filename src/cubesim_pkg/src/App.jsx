import React, { useState, useRef, useEffect } from 'react';
import { RotateCw, RotateCcw, RefreshCw, Eye } from 'lucide-react';
import * as THREE from 'three';

const CubeSimulator = () => {
  const mountRef = useRef(null);
  const sceneRef = useRef(null);
  const rendererRef = useRef(null);
  const cameraRef = useRef(null);
  const cubesRef = useRef({});
  const animationRef = useRef({ theta: Math.PI / 4, phi: Math.PI / 4 });
  const isDraggingRef = useRef(false);
  
  const [cubeState, setCubeState] = useState(() => initializeCube());
  const [history, setHistory] = useState([]);
  const [isRotating, setIsRotating] = useState(false);
  const [visualMode, setVisualMode] = useState('wheel');
  const [commandInput, setCommandInput] = useState('');
  const [isDragging, setIsDragging] = useState(false);
  const [previousMousePosition, setPreviousMousePosition] = useState({ x: 0, y: 0 });
  
  function initializeCube() {
    const state = {};
    for (let x = -1; x <= 1; x++) {
      for (let y = -1; y <= 1; y++) {
        for (let z = -1; z <= 1; z++) {
          const key = `${x},${y},${z}`;
          state[key] = { 
            x, y, z, 
            type: getPieceType(x, y, z),
            wheelType: getWheelType(x, y, z),
            originalKey: key,
            colors: {
              px: x === 1 ? 0x0000ff : null,
              nx: x === -1 ? 0x00ff00 : null,
              py: y === 1 ? 0xffffff : null,
              ny: y === -1 ? 0xffff00 : null,
              pz: z === 1 ? 0xff0000 : null,
              nz: z === -1 ? 0xff8800 : null
            }
          };
        }
      }
    }
    return state;
  }
  
  function getPieceType(x, y, z) {
    const faceCount = [x, y, z].filter(v => v === -1 || v === 1).length;
    if (faceCount === 0) return 'center';
    if (faceCount === 1) return 'center-face';
    if (faceCount === 2) return 'edge';
    return 'corner';
  }
  
  function getWheelType(x, y, z) {
    if (getPieceType(x, y, z) !== 'edge') return null;
    if ((x === 0 && y === -1 && z === 1) || (x === 0 && y === 1 && z === 1)) return null;
    
    if ((x === -1 && y === -1) || (x === 1 && y === -1)) return 'A';
    if ((x === -1 && y === 1) || (x === 1 && y === 1)) return 'B';
    return null;
  }
  
  function getCubeMaterials(piece, mode) {
    if (mode === 'wheel') {
      let color = 0x888888;
      if (piece.wheelType === 'A') color = 0x4ade80;
      if (piece.wheelType === 'B') color = 0x3b82f6;
      if (piece.originalKey === '0,1,1') color = 0xfbbf24;
      
      const opacity = (!piece.wheelType && piece.originalKey !== '0,1,1') ? 0.3 : 1;
      return new THREE.MeshPhongMaterial({ 
        color,
        transparent: opacity < 1,
        opacity
      });
    }
    
    if (mode === 'color' || mode === 'both') {
      const faceColors = [
        piece.colors.px || 0x202020,
        piece.colors.nx || 0x202020,
        piece.colors.py || 0x202020,
        piece.colors.ny || 0x202020,
        piece.colors.pz || 0x202020,
        piece.colors.nz || 0x202020
      ];
      
      const isImportant = piece.wheelType || piece.originalKey === '0,1,1';
      const opacity = (mode === 'both' && !isImportant) ? 0.3 : 1;
      
      const materials = faceColors.map(color => {
        return new THREE.MeshPhongMaterial({ 
          color,
          transparent: opacity < 1,
          opacity
        });
      });
      
      return materials;
    }
  }
  
  useEffect(() => {
    if (!mountRef.current) return;
    
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf0f0f0);
    sceneRef.current = scene;
    
    const camera = new THREE.PerspectiveCamera(75, mountRef.current.clientWidth / mountRef.current.clientHeight, 0.1, 1000);
    camera.position.set(5, 5, 5);
    camera.lookAt(0, 0, 0);
    cameraRef.current = camera;
    
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(mountRef.current.clientWidth, mountRef.current.clientHeight);
    mountRef.current.appendChild(renderer.domElement);
    rendererRef.current = renderer;
    
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(ambientLight);
    const directionalLight = new THREE.DirectionalLight(0xffffff, 0.5);
    directionalLight.position.set(10, 10, 10);
    scene.add(directionalLight);
    
    const gridHelper = new THREE.GridHelper(10, 10, 0xcccccc, 0xeeeeee);
    scene.add(gridHelper);
    
    const axesHelper = new THREE.AxesHelper(3);
    scene.add(axesHelper);
    
    const createTextSprite = (text, color) => {
      const canvas = document.createElement('canvas');
      const context = canvas.getContext('2d');
      canvas.width = 256;
      canvas.height = 256;
      context.font = 'Bold 120px Arial';
      context.fillStyle = color;
      context.textAlign = 'center';
      context.textBaseline = 'middle';
      context.fillText(text, 128, 128);
      
      const texture = new THREE.CanvasTexture(canvas);
      const spriteMaterial = new THREE.SpriteMaterial({ map: texture });
      const sprite = new THREE.Sprite(spriteMaterial);
      sprite.scale.set(0.8, 0.8, 1);
      return sprite;
    };
    
    const xLabel = createTextSprite('X', '#ff0000');
    xLabel.position.set(3.5, 0, 0);
    scene.add(xLabel);
    
    const yLabel = createTextSprite('Y', '#00ff00');
    yLabel.position.set(0, 3.5, 0);
    scene.add(yLabel);
    
    const zLabel = createTextSprite('Z', '#0000ff');
    zLabel.position.set(0, 0, 3.5);
    scene.add(zLabel);
    
    let autoRotateAngle = animationRef.current.theta;
    function animate() {
      requestAnimationFrame(animate);
      
      if (!isDraggingRef.current) {
        autoRotateAngle += 0.003;
        animationRef.current.theta = autoRotateAngle;
      } else {
      autoRotateAngle = animationRef.current.theta;
    }
      
      const radius = 7;
      camera.position.x = radius * Math.sin(animationRef.current.phi) * Math.cos(animationRef.current.theta);
      camera.position.y = radius * Math.cos(animationRef.current.phi);
      camera.position.z = radius * Math.sin(animationRef.current.phi) * Math.sin(animationRef.current.theta);
      camera.lookAt(0, 0, 0);
      
      renderer.render(scene, camera);
    }
    animate();
    
    return () => {
      if (mountRef.current && renderer.domElement) {
        mountRef.current.removeChild(renderer.domElement);
      }
      renderer.dispose();
    };
  }, []);
  
  useEffect(() => {
    if (!sceneRef.current) return;
    
    Object.values(cubesRef.current).forEach(cube => {
      sceneRef.current.remove(cube);
    });
    cubesRef.current = {};
    
    Object.entries(cubeState).forEach(([key, piece]) => {
      const geometry = new THREE.BoxGeometry(0.9, 0.9, 0.9);
      const materials = getCubeMaterials(piece, visualMode);
      const cube = new THREE.Mesh(geometry, materials);
      
      cube.position.x = piece.x;
      cube.position.y = piece.y;
      cube.position.z = piece.z;
      
      const edges = new THREE.EdgesGeometry(geometry);
      const line = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: 0x000000, linewidth: 2 }));
      cube.add(line);
      
      sceneRef.current.add(cube);
      cubesRef.current[key] = cube;
    });
  }, [cubeState, visualMode]);
  
  function rotateFace(face, layer, clockwise) {
    if (isRotating) return;
    setIsRotating(true);
    
    const newState = JSON.parse(JSON.stringify(cubeState));
    const pieces = Object.values(newState);
    
    pieces.forEach(piece => {
      let x = piece.x;
      let y = piece.y;
      let z = piece.z;
      let colors = piece.colors;
      let newX = x;
      let newY = y;
      let newZ = z;
      let newColors = { ...colors };
      let shouldRotate = false;
      
      if (face === 'F') { // Z축 회전
        shouldRotate = (layer === null && z === 1) || (layer === 'S' && z === 0);
        if (shouldRotate) {
          if (clockwise) {
            newX = -y;
            newY = x;
            // 시계방향: Top(py) -> Right(px), Right(px) -> Bottom(ny), ...
            newColors.px = colors.py;
            newColors.py = colors.nx;
            newColors.nx = colors.ny;
            newColors.ny = colors.px;
          } else {
            newX = y;
            newY = -x;
            newColors.px = colors.ny;
            newColors.py = colors.px;
            newColors.nx = colors.py;
            newColors.ny = colors.nx;
          }
        }
      } else if (face === 'B') { // Z축 회전 (F와 반대 면)
        shouldRotate = (layer === null && z === -1) || (layer === 'S' && z === 0);
        if (shouldRotate) {
          if (clockwise) {
            newX = y;
            newY = -x;
            // B 시계방향은 F 반시계와 유사한 축 방향
            newColors.px = colors.ny;
            newColors.py = colors.px;
            newColors.nx = colors.py;
            newColors.ny = colors.nx;
          } else {
            newX = -y;
            newY = x;
            newColors.px = colors.py;
            newColors.py = colors.nx;
            newColors.nx = colors.ny;
            newColors.ny = colors.px;
          }
        }
      } else if (face === 'U') { // Y축 회전
        shouldRotate = (layer === null && y === 1) || (layer === 'E' && y === 0);
        if (shouldRotate) {
          if (clockwise) {
            newX = z;
            newZ = -x;
            // 시계방향: Front(pz) -> Right(px), Right(px) -> Back(nz), ...
            newColors.px = colors.pz;
            newColors.pz = colors.nx;
            newColors.nx = colors.nz;
            newColors.nz = colors.px;
          } else {
            newX = -z;
            newZ = x;
            newColors.px = colors.nz;
            newColors.pz = colors.px;
            newColors.nx = colors.pz;
            newColors.nz = colors.nx;
          }
        }
      } else if (face === 'D') { // Y축 회전
        shouldRotate = (layer === null && y === -1) || (layer === 'E' && y === 0);
        if (shouldRotate) {
          if (clockwise) {
            newX = -z;
            newZ = x;
            newColors.px = colors.nz;
            newColors.pz = colors.px;
            newColors.nx = colors.pz;
            newColors.nz = colors.nx;
          } else {
            newX = z;
            newZ = -x;
            newColors.px = colors.pz;
            newColors.pz = colors.nx;
            newColors.nx = colors.nz;
            newColors.nz = colors.px;
          }
        }
      } else if (face === 'R') { // X축 회전
        shouldRotate = (layer === null && x === 1) || (layer === 'M' && x === 0);
        if (shouldRotate) {
          if (clockwise) {
            newY = -z;
            newZ = y;
            // 시계방향: Front(pz) -> Top(py), Top(py) -> Back(nz), ...
            newColors.py = colors.pz;
            newColors.pz = colors.ny;
            newColors.ny = colors.nz;
            newColors.nz = colors.py;
          } else {
            newY = z;
            newZ = -y;
            newColors.py = colors.nz;
            newColors.pz = colors.py;
            newColors.ny = colors.pz;
            newColors.nz = colors.ny;
          }
        }
      } else if (face === 'L') { // X축 회전
        shouldRotate = (layer === null && x === -1) || (layer === 'M' && x === 0);
        if (shouldRotate) {
          if (clockwise) {
            newY = z;
            newZ = -y;
            newColors.py = colors.nz;
            newColors.pz = colors.py;
            newColors.ny = colors.pz;
            newColors.nz = colors.ny;
          } else {
            newY = -z;
            newZ = y;
            newColors.py = colors.pz;
            newColors.pz = colors.ny;
            newColors.ny = colors.nz;
            newColors.nz = colors.py;
          }
        }
      }
      
      piece.x = newX;
      piece.y = newY;
      piece.z = newZ;
      piece.colors = newColors;
    });
    
    const reconstructed = {};
    pieces.forEach(piece => {
      const key = `${piece.x},${piece.y},${piece.z}`;
      reconstructed[key] = piece;
    });
    
    const notation = layer ? `${layer}${clockwise ? '' : "'"}` : `${face}${clockwise ? '' : "'"}`;
    setCubeState(reconstructed);
    setHistory(prev => [...prev, notation]);
    
    setTimeout(() => setIsRotating(false), 300);
  }
  
  function executeCommands(commandStr) {
    const commands = commandStr.trim().toUpperCase().split(/\s+/);
    const validCommands = ['F', "F'", 'B', "B'", 'U', "U'", 'D', "D'", 'R', "R'", 'L', "L'", 
                          'S', "S'", 'E', "E'", 'M', "M'"];
    
    let delay = 0;
    commands.forEach((cmd) => {
      if (!validCommands.includes(cmd)) {
        alert(`잘못된 명령어: ${cmd}`);
        return;
      }
      
      setTimeout(() => {
        const isPrime = cmd.endsWith("'");
        const baseFace = cmd.replace("'", "");
        
        if (['S', 'E', 'M'].includes(baseFace)) {
          const faceMap = { 'S': 'F', 'E': 'U', 'M': 'R' };
          rotateFace(faceMap[baseFace], baseFace, !isPrime);
        } else {
          rotateFace(baseFace, null, !isPrime);
        }
      }, delay);
      
      delay += 350;
    });
  }
  
  const handleMouseDown = (e) => {
    setIsDragging(true);
    isDraggingRef.current = true;
    setPreviousMousePosition({ x: e.clientX, y: e.clientY });
  };
  
  const handleMouseMove = (e) => {
    if (!isDraggingRef.current) return;
    
    const deltaX = e.clientX - previousMousePosition.x;
    const deltaY = e.clientY - previousMousePosition.y;
    
    animationRef.current.theta = animationRef.current.theta + deltaX * 0.01;
    animationRef.current.phi = Math.max(0.1, Math.min(Math.PI - 0.1, animationRef.current.phi + deltaY * 0.01));
    
    setPreviousMousePosition({ x: e.clientX, y: e.clientY });
  };
  
  const handleMouseUp = () => {
    setIsDragging(false);
    isDraggingRef.current = false;
  };
  
  function reset() {
    setCubeState(initializeCube());
    setHistory([]);
  }
  
  const wheelPieces = Object.values(cubeState).filter(p => p.wheelType);
  const aWheels = wheelPieces.filter(p => p.wheelType === 'A');
  const bWheels = wheelPieces.filter(p => p.wheelType === 'B');
  const specialPiece = Object.values(cubeState).find(p => p.originalKey === '0,1,1');
  
  const notations = {
    F: "Front (정면, z=1)",
    B: "Back (뒤, z=-1)",
    U: "Up (위, y=1)",
    D: "Down (아래, y=-1)",
    R: "Right (오른쪽, x=1)",
    L: "Left (왼쪽, x=-1)",
    S: "Slice (앞뒤 중간층, z=0)",
    E: "Equator (위아래 중간층, y=0)",
    M: "Middle (좌우 중간층, x=0)"
  };
  
  return (
    <div className="p-6 max-w-6xl mx-auto">
      <h1 className="text-2xl font-bold mb-4">3×3 Rubik's Cube Simulator</h1>
      
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <div 
            ref={mountRef} 
            className="w-full bg-white rounded-lg shadow-lg cursor-grab active:cursor-grabbing"
            style={{ height: '500px' }}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
          />
          
          <div className="mt-3 flex gap-2">
            <button
              onClick={() => setVisualMode('wheel')}
              className={`flex-1 px-3 py-2 rounded text-sm font-medium ${
                visualMode === 'wheel' ? 'bg-blue-500 text-white' : 'bg-gray-200 text-gray-700'
              }`}
            >
              <Eye className="inline w-4 h-4 mr-1" />
              강조 모드
            </button>
            <button
              onClick={() => setVisualMode('color')}
              className={`flex-1 px-3 py-2 rounded text-sm font-medium ${
                visualMode === 'color' ? 'bg-blue-500 text-white' : 'bg-gray-200 text-gray-700'
              }`}
            >
              <Eye className="inline w-4 h-4 mr-1" />
              색상 모드
            </button>
            <button
              onClick={() => setVisualMode('both')}
              className={`flex-1 px-3 py-2 rounded text-sm font-medium ${
                visualMode === 'both' ? 'bg-blue-500 text-white' : 'bg-gray-200 text-gray-700'
              }`}
            >
              <Eye className="inline w-4 h-4 mr-1" />
              종합 모드
            </button>
          </div>
          
          <div className="mt-2 text-sm text-gray-600 space-y-1">
            {visualMode === 'wheel' && (
              <>
                <div>🟢 녹색: A타입 바퀴 ({aWheels.length}개)</div>
                <div>🔵 파랑: B타입 바퀴 ({bWheels.length}개)</div>
                <div>🟡 노랑: 특수 조각 (0,1,1)</div>
                <div>⚪ 회색(반투명): 일반 조각</div>
              </>
            )}
            {visualMode === 'color' && (
              <>
                <div>🔴 빨강(F): 정면 z=1 / 🟠 주황(B): 뒤 z=-1</div>
                <div>⚪ 흰색(U): 위 y=1 / 🟡 노랑(D): 아래 y=-1</div>
                <div>🔵 파랑(R): 오른쪽 x=1 / 🟢 초록(L): 왼쪽 x=-1</div>
              </>
            )}
            {visualMode === 'both' && (
              <div>각 면의 색상 표시 + 바퀴/특수 조각은 불투명, 나머지는 반투명</div>
            )}
          </div>
        </div>
        
        <div className="space-y-4">
          <div className="bg-purple-50 p-4 rounded-lg">
            <h2 className="font-semibold mb-3">명령어 입력</h2>
            <div className="space-y-2">
              <input
                type="text"
                value={commandInput}
                onChange={(e) => setCommandInput(e.target.value)}
                placeholder="ex: F R U' D S E'"
                className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                onKeyPress={(e) => {
                  if (e.key === 'Enter' && !isRotating) {
                    executeCommands(commandInput);
                    setCommandInput('');
                  }
                }}
              />
              <button
                onClick={() => {
                  executeCommands(commandInput);
                  setCommandInput('');
                }}
                disabled={isRotating || !commandInput.trim()}
                className="w-full bg-purple-500 text-white px-4 py-2 rounded hover:bg-purple-600 disabled:opacity-50 text-sm"
              >
                실행
              </button>
              <div className="text-xs text-gray-600">
                여러 명령어를 공백으로 구분하여 입력 (예: F R U')
              </div>
            </div>
          </div>
          
          <div className="bg-blue-50 p-4 rounded-lg">
            <h2 className="font-semibold mb-3">기본 회전</h2>
            
            {/* 위쪽: U */}
            <div className="flex justify-center mb-2">
              <div className="flex gap-1">
                <button onClick={() => rotateFace('U', null, true)} disabled={isRotating}
                  className="bg-blue-500 text-white px-3 py-2 rounded text-xs disabled:opacity-50">
                  U <RotateCw className="inline w-3 h-3" />
                </button>
                <button onClick={() => rotateFace('U', null, false)} disabled={isRotating}
                  className="bg-blue-400 text-white px-3 py-2 rounded text-xs disabled:opacity-50">
                  U' <RotateCcw className="inline w-3 h-3" />
                </button>
              </div>
            </div>
            
            {/* 중간: L F R B */}
            <div className="grid grid-cols-4 gap-2 mb-2">
              <div className="flex flex-col gap-1">
                <button onClick={() => rotateFace('L', null, true)} disabled={isRotating}
                  className="bg-blue-500 text-white px-2 py-2 rounded text-xs disabled:opacity-50">
                  L <RotateCw className="inline w-3 h-3" />
                </button>
                <button onClick={() => rotateFace('L', null, false)} disabled={isRotating}
                  className="bg-blue-400 text-white px-2 py-2 rounded text-xs disabled:opacity-50">
                  L' <RotateCcw className="inline w-3 h-3" />
                </button>
              </div>
              
              <div className="flex flex-col gap-1">
                <button onClick={() => rotateFace('R', null, true)} disabled={isRotating}
                  className="bg-blue-500 text-white px-2 py-2 rounded text-xs disabled:opacity-50">
                  R <RotateCw className="inline w-3 h-3" />
                </button>
                <button onClick={() => rotateFace('R', null, false)} disabled={isRotating}
                  className="bg-blue-400 text-white px-2 py-2 rounded text-xs disabled:opacity-50">
                  R' <RotateCcw className="inline w-3 h-3" />
                </button>
              </div>
              
              <div className="flex flex-col gap-1">
                <button onClick={() => rotateFace('B', null, true)} disabled={isRotating}
                  className="bg-blue-500 text-white px-2 py-2 rounded text-xs disabled:opacity-50">
                  B <RotateCw className="inline w-3 h-3" />
                </button>
                <button onClick={() => rotateFace('B', null, false)} disabled={isRotating}
                  className="bg-blue-400 text-white px-2 py-2 rounded text-xs disabled:opacity-50">
                  B' <RotateCcw className="inline w-3 h-3" />
                </button>
              </div>
            </div>
          </div>
          
          <button
            onClick={reset}
            className="w-full bg-gray-500 text-white px-4 py-2 rounded hover:bg-gray-600 flex items-center justify-center gap-2"
          >
            <RefreshCw className="w-4 h-4" />
            초기화
          </button>
          
          <div className="bg-gray-50 p-4 rounded-lg">
            <h3 className="font-semibold mb-2">회전 기록</h3>
            <div className="text-xs font-mono bg-white p-2 rounded min-h-[60px] max-h-[120px] overflow-y-auto">
              {history.join(' ') || '(없음)'}
            </div>
            <div className="text-xs text-gray-600 mt-1">
              총 {history.length}회 회전
            </div>
          </div>
          
          <div className="bg-yellow-50 p-4 rounded-lg">
            <h3 className="font-semibold mb-2">특수 조각 추적</h3>
            <div className="text-sm">
              <div className="mb-1">
                원래: (0, 1, 1)
              </div>
              <div className="mb-1">
                현재: {specialPiece ? 
                  `(${specialPiece.x}, ${specialPiece.y}, ${specialPiece.z})` : 
                  '찾을 수 없음'}
              </div>
              <div className="text-xs text-gray-600">
                {specialPiece && specialPiece.x === 0 && specialPiece.y === 1 && specialPiece.z === 1 ? 
                  '✅ 원래 위치' : '⚠️ 이동됨'}
              </div>
            </div>
          </div>
          
          <div className="bg-gray-100 p-3 rounded text-xs space-y-1">
            <strong>회전 명령어:</strong>
            {Object.entries(notations).map(([key, desc]) => (
              <div key={key}>{key}: {desc}</div>
            ))}
            <div className="mt-2 pt-2 border-t border-gray-300">
              ' (프라임): 반시계 방향 회전
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default CubeSimulator;