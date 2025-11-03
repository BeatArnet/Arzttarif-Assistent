// questionsData is provided globally by questions.js

// 1. Canvas and Context
const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');
const canvasWidth = canvas.width;
const canvasHeight = canvas.height;

// Game Constants
const PADDLE_WIDTH = 100;
const PADDLE_HEIGHT = 20;
const PADDLE_SPEED = 8;
const BALL_RADIUS = 10;
let maxBallSpeedX = 6; // For paddle collision adjustment
const BALL_TRAIL_MAX_LENGTH = 15;

const BRICK_WIDTH = 70;
const BRICK_HEIGHT = 25;
const BRICK_PADDING = 10;
const BRICK_ROWS = 5;
const BRICKS_PER_ROW = 10;
const BRICK_START_X = (canvasWidth - (BRICKS_PER_ROW * (BRICK_WIDTH + BRICK_PADDING) - BRICK_PADDING)) / 2;
const BRICK_START_Y = 50;
const BRICK_COLORS = ["#005EB8", "#0f2f68", "#00856F", "#1B4C8C", "#4AA3D2"];
const PADDLE_COLORS = ["#00856F", "#005EB8", "#1B4C8C", "#4AA3D2"];
const BALL_COLOR = "#005EB8";
const BALL_TRAIL_COLOR = "rgba(0, 94, 184, 0.18)";

// Score
let score = 0;
const scoreDisplay = document.getElementById('scoreDisplay');

// Sound Buffers
const gameSounds = {};
let soundsLoadedCount = 0;
const soundFiles = {
    'brick_hit': '/brick_quiz/assets/sounds/brick_hit.wav',
    'paddle_hit': '/brick_quiz/assets/sounds/paddle_hit.wav',
    'wall_hit': '/brick_quiz/assets/sounds/wall_hit.wav',
    'game_over': '/brick_quiz/assets/sounds/game_over.wav'
};
const totalSoundsToLoad = Object.keys(soundFiles).length;

// Quiz Statistics
let questionsAnsweredCorrectly = 0;
let questionsAnsweredTotal = 0;

// Game State
let gameIsOver = false;

// Quiz State Variables
let quizActive = false;
let currentQuestion = null;
let questionBrickTarget = 0;
let brickHitCount = 0; 
let ballSpeedBoostActive = false;
let boostStartTime = 0;
let originalBallSpeedX = 0;
let originalBallSpeedY = 0;
let usedQuestionIndices = []; 
let shuffledQuizQueue = []; 

// Keyboard Navigation States
let selectedAnswerIndex = -1; 
let quizNavActive = false;    
let gameEndNavActive = false; 

// DOM Elements
const quizPopup = document.getElementById('quizPopup');
const quizTitle = document.getElementById('quizTitle');
const quizQuestionEl = document.getElementById('quizQuestion');
const quizAnswersEl = document.getElementById('quizAnswers');
const quizFeedback = document.getElementById('quizFeedback');
let gameEndPlayAgainButton;

document.addEventListener('DOMContentLoaded', () => {
    gameEndPlayAgainButton = document.getElementById('gameEndPlayAgainButton');
    if (gameEndPlayAgainButton) {
        gameEndPlayAgainButton.addEventListener('click', () => {
            const gameEndPopup = document.getElementById('gameEndPopup');
            if (gameEndPopup) gameEndPopup.style.display = 'none';
            gameEndNavActive = false;
            gameEndPlayAgainButton.classList.remove('game-end-button-active');
            resetGame();
        });
    }
});

const loadingScreen = document.getElementById('loadingScreen');
const gameContainer = document.getElementById('gameContainer');
// const startPrompt = document.getElementById('startPrompt'); // This line was removed in the previous step

// Keyboard control flags (for paddle)
let arrowLeftPressed = false;
let arrowRightPressed = false;

// Utility Function for Shuffling
function shuffleArray(array) {
    for (let i = array.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [array[i], array[j]] = [array[j], array[i]];
    }
}

function lightenColor(color, percent) {
    const num = parseInt(color.slice(1), 16);
    const amt = Math.round(2.55 * percent);
    let R = (num >> 16) + amt;
    let G = (num >> 8 & 0x00FF) + amt;
    let B = (num & 0x0000FF) + amt;
    R = R < 255 ? (R < 0 ? 0 : R) : 255;
    G = G < 255 ? (G < 0 ? 0 : G) : 255;
    B = B < 255 ? (B < 0 ? 0 : B) : 255;
    return `#${(1 << 24 | R << 16 | G << 8 | B).toString(16).slice(1)}`;
}

function drawRoundedRect(ctx, x, y, width, height, radius) {
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + width - radius, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
    ctx.lineTo(x + width, y + height - radius);
    ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
    ctx.lineTo(x + radius, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
    ctx.lineTo(x, y + radius);
    ctx.quadraticCurveTo(x, y, x + radius, y);
    ctx.closePath();
}

function updateScoreDisplay() {
    scoreDisplay.textContent = `Punktestand: ${score}`;
}

// 2. Asset Loading
function loadSound(name, filePath) {
    return new Promise((resolve) => {
        const audio = new Audio(filePath);
        audio.addEventListener('canplaythrough', () => {
            gameSounds[name] = audio;
            soundsLoadedCount++;
            resolve();
        }, { once: true });
        audio.addEventListener('error', (e) => {
            console.error(`Error loading sound ${name} from ${filePath}:`, e);
            resolve();
        }, { once: true });
        audio.load();
    });
}

async function loadAllSounds() {
    const soundPromises = Object.keys(soundFiles).map(name => loadSound(name, soundFiles[name]));
    try { await Promise.all(soundPromises); }
    catch (error) { console.error('Error loading one or more sounds (Promise.all rejected):', error); }
}

function playSound(soundName) {
    const baseSound = gameSounds[soundName];
    if (!baseSound) return;
    const sound = baseSound.cloneNode();
    sound.volume = 0.7;
    sound.playbackRate = 1 + (Math.random() * 0.2 - 0.1);
    sound.play().catch(e => console.error(`Error playing sound ${soundName}:`, e));
}

let quizQuestions = window.questionsData || [];
function loadQuestions() { quizQuestions = window.questionsData || []; }

// 3. Game Entities (Paddle, Ball, Brick classes remain unchanged)
class Paddle { 
    constructor() {
        this.width = PADDLE_WIDTH; this.height = PADDLE_HEIGHT;
        this.x = (canvasWidth - this.width) / 2; this.y = canvasHeight - this.height - 10; 
        this.color = PADDLE_COLORS[0]; this.speed = PADDLE_SPEED;
    }
    draw(ctx) { ctx.fillStyle = this.color; ctx.fillRect(this.x, this.y, this.width, this.height); }
    changeColor() {
        const currentIndex = PADDLE_COLORS.indexOf(this.color);
        this.color = PADDLE_COLORS[(currentIndex + 1) % PADDLE_COLORS.length];
    }
}
class Ball {
    constructor() {
        this.radius = BALL_RADIUS; this.x = canvasWidth / 2; this.y = canvasHeight / 2;
        this.color = BALL_COLOR; this.dx = 4;  this.dy = -4;
        this.trail = [];
    }
    draw(ctx) {
        ctx.save();
        for (let i = 0; i < this.trail.length; i++) {
            const pos = this.trail[i];
            const alpha = (i + 1) / this.trail.length * 0.5;
            ctx.globalAlpha = alpha;
            ctx.beginPath();
            ctx.arc(pos.x, pos.y, this.radius, 0, Math.PI * 2);
            ctx.fillStyle = BALL_TRAIL_COLOR;
            ctx.fill();
            ctx.closePath();
        }
        ctx.restore();
        const gradient = ctx.createRadialGradient(
            this.x,
            this.y,
            this.radius * 0.2,
            this.x,
            this.y,
            this.radius
        );
        gradient.addColorStop(0, "#ffffff");
        gradient.addColorStop(1, this.color);
        ctx.beginPath();
        ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
        ctx.fillStyle = gradient;
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.strokeStyle = "rgba(255, 255, 255, 0.6)";
        ctx.stroke();
        ctx.closePath();
    }
    update() {
        this.x += this.dx; this.y += this.dy;
        if (this.x + this.radius > canvasWidth || this.x - this.radius < 0) { this.dx *= -1; playSound('wall_hit'); }
        if (this.y - this.radius < 0) { this.dy *= -1; playSound('wall_hit'); }
        if (this.y + this.radius > canvasHeight) { playSound('game_over'); showGameEndPopup(); return; }
        if (this.dy > 0 && this.x + this.radius > paddle.x && this.x - this.radius < paddle.x + paddle.width &&
            this.y + this.radius > paddle.y && this.y - this.radius < paddle.y + paddle.height) {
            this.dy *= -1; this.y = paddle.y - this.radius;
            this.dx = ((this.x - (paddle.x + paddle.width / 2)) / (paddle.width / 2)) * maxBallSpeedX;
            playSound('paddle_hit'); paddle.changeColor();
        }
        for (let i = 0; i < bricks.length; i++) {
            const brick = bricks[i];
            const closestX = Math.max(brick.x, Math.min(this.x, brick.x + brick.width));
            const closestY = Math.max(brick.y, Math.min(this.y, brick.y + brick.height));
            const dX = this.x - closestX; const dY = this.y - closestY;
            if ((dX * dX + dY * dY) < (this.radius * this.radius)) {
                // remove brick from active list to reduce future iterations
                bricks.splice(i, 1);
                score += 10; updateScoreDisplay(); playSound('brick_hit'); brickHitCount++;
                if (brickHitCount % 10 === 0) {
                    this.dx *= 1.1;
                    this.dy *= 1.1;
                    this.dx = Math.max(-12, Math.min(12, this.dx));
                    this.dy = Math.max(-12, Math.min(12, this.dy));
                    maxBallSpeedX *= 1.1;
                }
                const oX = this.radius - Math.abs(dX); const oY = this.radius - Math.abs(dY);
                if (oX + 0.1 < oY) { this.dx *= -1; this.x += this.dx > 0 ? oX : -oX; }
                else if (oY + 0.1 < oX) { this.dy *= -1; this.y += this.dy > 0 ? oY : -oY; }
                else { this.dx *= -1; this.dy *= -1; this.x += this.dx > 0 ? oX : -oX; this.y += this.dy > 0 ? oY : -oY; }
                if (brick.isQuestionBrick) { quizActive = true; startQuiz(); }
                break;
            }
        }
        this.trail.push({ x: this.x, y: this.y });
        if (this.trail.length > BALL_TRAIL_MAX_LENGTH) this.trail.shift();
    }
}
class Brick {
    constructor(x, y, width, height, color) {
        this.x = x; this.y = y; this.width = width; this.height = height;
        this.color = color; this.isQuestionBrick = false;
    }
    draw(ctx) {
        const radius = 6;
        const gradient = ctx.createLinearGradient(this.x, this.y, this.x, this.y + this.height);
        gradient.addColorStop(0, lightenColor(this.color, 30));
        gradient.addColorStop(1, this.color);
        drawRoundedRect(ctx, this.x, this.y, this.width, this.height, radius);
        ctx.fillStyle = gradient;
        ctx.fill();
        ctx.strokeStyle = '#ffffff55';
        ctx.lineWidth = 2;
        ctx.stroke();
        if (this.isQuestionBrick) {
            const qT = "?"; const x = this.x + this.width / 2; const y = this.y + this.height / 2;
            ctx.font = "bold 16px Consolas"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
            ctx.fillStyle = "rgba(220,220,220,0.7)"; const o = 1;
            ctx.fillText(qT, x-o, y-o); ctx.fillText(qT, x+o, y-o); ctx.fillText(qT, x-o, y+o); ctx.fillText(qT, x+o, y+o);
            ctx.fillStyle = "black"; ctx.fillText(qT, x, y);
        }
    }
}
let bricks = [];
function initializeBricks() { 
    bricks = []; createdBrickCount = 0; 
    questionBrickTarget = Math.floor(Math.random() * 3) + 6; 
    for (let r = 0; r < BRICK_ROWS; r++) {
        for (let c = 0; c < BRICKS_PER_ROW; c++) {
            createdBrickCount++;
            const brick = new Brick(
                BRICK_START_X + c * (BRICK_WIDTH + BRICK_PADDING),
                BRICK_START_Y + r * (BRICK_HEIGHT + BRICK_PADDING),
                BRICK_WIDTH, BRICK_HEIGHT, BRICK_COLORS[r % BRICK_COLORS.length]
            );
            if (createdBrickCount === questionBrickTarget) {
                brick.isQuestionBrick = true;
                questionBrickTarget += Math.floor(Math.random() * 3) + 6;
            }
            bricks.push(brick);
        }
    }
}

// 4. Rendering Function (drawGame remains unchanged)
function drawGame() { 
    ctx.clearRect(0, 0, canvasWidth, canvasHeight);
    const gradient = ctx.createLinearGradient(0, 0, 0, canvasHeight);
    gradient.addColorStop(0, "rgba(0, 94, 184, 0.18)");
    gradient.addColorStop(1, "rgba(0, 133, 111, 0.18)");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, canvasWidth, canvasHeight);
    paddle.draw(ctx); ball.draw(ctx);
    for (let i = 0; i < bricks.length; i++) {
        bricks[i].draw(ctx);
    }
}

// Update game state (update remains unchanged)
function update() { 
    if (gameIsOver || quizActive) return; 
    if (ballSpeedBoostActive && Date.now() - boostStartTime >= 10000) {
        ball.dx = originalBallSpeedX; ball.dy = originalBallSpeedY;
        ballSpeedBoostActive = false;
    } 
    
    if (arrowLeftPressed) {
        paddle.x -= PADDLE_SPEED;
    }
    if (arrowRightPressed) {
        paddle.x += PADDLE_SPEED;
    }

    if (paddle.x < 0) paddle.x = 0;
    if (paddle.x + paddle.width > canvas.width) paddle.x = canvas.width - paddle.width;
    
    ball.update(); checkWinCondition(); 
}

// Quiz Functions (getNewQuizQuestion, updateQuizAnswerSelectionVisuals, startQuiz, handleAnswer, endQuiz remain unchanged)
function getNewQuizQuestion() { 
    if (shuffledQuizQueue.length === 0) {
        if (quizQuestions.length === 0) return null;
        shuffledQuizQueue = quizQuestions.map((_, i) => i); shuffleArray(shuffledQuizQueue);
        shuffledQuizQueue = shuffledQuizQueue.map(i => quizQuestions[i]);
    }
    return shuffledQuizQueue.pop();
}

function updateQuizAnswerSelectionVisuals() {
    const buttons = quizAnswersEl.getElementsByTagName('button');
    if (!buttons.length) return; 

    for (let i = 0; i < buttons.length; i++) {
        if (i === selectedAnswerIndex) {
            buttons[i].classList.add('selected-answer-keyboard');
        } else {
            buttons[i].classList.remove('selected-answer-keyboard');
        }
    }
}

function startQuiz() {
    currentQuestion = getNewQuizQuestion();
    if (!currentQuestion) { quizActive = false; return; }
    quizTitle.textContent = currentQuestion.title;
    quizQuestionEl.textContent = currentQuestion.question;
    quizAnswersEl.innerHTML = ''; 
    currentQuestion.answers.forEach((answer, index) => { 
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'quiz-answer-btn';
        button.textContent = answer;
        button.onclick = () => handleAnswer(index); 
        quizAnswersEl.appendChild(button);
    });
    quizFeedback.textContent = '';
    quizFeedback.classList.remove('feedback-success', 'feedback-error');
    quizPopup.style.display = 'block';
    
    selectedAnswerIndex = 0; 
    quizNavActive = true;   
    updateQuizAnswerSelectionVisuals(); 
}

function handleAnswer(selectedIndexParam) {
    if (!currentQuestion) return; 
    
    const actualSelectedIndex = selectedIndexParam; 
    
    const buttons = quizAnswersEl.getElementsByTagName('button');
    const stateClasses = ['answer-correct', 'answer-incorrect', 'answer-neutral'];
    for (let i = 0; i < buttons.length; i++) {
        buttons[i].disabled = true; 
        buttons[i].classList.remove(...stateClasses, 'selected-answer-keyboard');
        if (i === currentQuestion.correct_answer_index) {
            buttons[i].classList.add('answer-correct');
        } else if (i === actualSelectedIndex) {
            buttons[i].classList.add('answer-incorrect');
        } else {
            buttons[i].classList.add('answer-neutral');
        }
    }
    questionsAnsweredTotal++;
    quizFeedback.classList.remove('feedback-success', 'feedback-error');
    if (actualSelectedIndex === currentQuestion.correct_answer_index) {
        questionsAnsweredCorrectly++; score += 100; 
        quizFeedback.textContent = "+100 Punkte"; 
        quizFeedback.classList.add('feedback-success');
    } else {
        score -= 20; score = Math.max(0, score); 
        quizFeedback.textContent = "-20 Punkte"; 
        quizFeedback.classList.add('feedback-error');
        if (!ballSpeedBoostActive) {
            ballSpeedBoostActive = true; originalBallSpeedX = ball.dx; originalBallSpeedY = ball.dy;
            ball.dx *= 1.5; ball.dy *= 1.5;
            ball.dx = Math.max(-9, Math.min(9, ball.dx)); ball.dy = Math.max(-9, Math.min(9, ball.dy));
            boostStartTime = Date.now();
        }
    }
    updateScoreDisplay();
    setTimeout(endQuiz, 2000); 
}

function endQuiz() {
    quizPopup.style.display = 'none';
    quizActive = false;
    currentQuestion = null; 
    
    quizNavActive = false; 
    selectedAnswerIndex = -1; 
    
    const buttons = quizAnswersEl.getElementsByTagName('button');
    for (let i = 0; i < buttons.length; i++) {
        buttons[i].classList.remove('selected-answer-keyboard');
    }
    
    checkWinCondition(); 
}

// resetGame, checkWinCondition, showGameEndPopup remain unchanged
function resetGame() {
    score = 0; updateScoreDisplay(); initializeBricks();
    paddle.x = (canvasWidth - PADDLE_WIDTH) / 2; paddle.y = canvasHeight - PADDLE_HEIGHT - 10;
    paddle.color = PADDLE_COLORS[0];
    ball.x = canvasWidth / 2; ball.y = canvasHeight / 2;
    ball.dx = 4; ball.dy = -4; ball.trail = [];
    quizActive = false; gameIsOver = false;
    if (ballSpeedBoostActive) { ball.dx = originalBallSpeedX; ball.dy = originalBallSpeedY; ballSpeedBoostActive = false; }
    brickHitCount = 0; questionsAnsweredCorrectly = 0; questionsAnsweredTotal = 0; maxBallSpeedX = 6;
    shuffledQuizQueue = [];
    if (quizQuestions.length > 0) {
        shuffledQuizQueue = quizQuestions.map((_, i) => i); shuffleArray(shuffledQuizQueue);
        shuffledQuizQueue = shuffledQuizQueue.map(i => quizQuestions[i]);
    }
    usedQuestionIndices = []; 
    
    quizNavActive = false; selectedAnswerIndex = -1; 
    gameEndNavActive = false; 
    if (gameEndPlayAgainButton) { 
        gameEndPlayAgainButton.classList.remove('game-end-button-active');
    }
}

function checkWinCondition() {
    if (!bricks) return;
    if (bricks.length === 0 && !quizActive) showGameEndPopup();
}

function showGameEndPopup() { 
    gameIsOver = true; 
    gameEndNavActive = true; 
    if (gameEndPlayAgainButton) {
        gameEndPlayAgainButton.classList.add('game-end-button-active');
    }

    const gameEndPopup = document.getElementById('gameEndPopup');
    const gameEndTitle = document.getElementById('gameEndTitle');
    const gameEndScore = document.getElementById('gameEndScore');
    const gameEndCorrect = document.getElementById('gameEndCorrect');
    const gameEndIncorrect = document.getElementById('gameEndIncorrect');
    if (!gameEndPopup || !gameEndTitle || !gameEndScore || !gameEndCorrect || !gameEndIncorrect) {
        alert(`Spielende!\nEndpunktestand: ${score}\nFragen: ${questionsAnsweredCorrectly} richtig / ${questionsAnsweredTotal} insgesamt`);
        return;
    }
    const incorrectAnswers = questionsAnsweredTotal - questionsAnsweredCorrectly;
    gameEndTitle.textContent = "Spielende"; 
    gameEndScore.textContent = `Endpunktestand: ${score}`;
    gameEndCorrect.textContent = `Richtige Antworten: ${questionsAnsweredCorrectly}`;
    gameEndIncorrect.textContent = `Falsche Antworten: ${incorrectAnswers}`;
    gameEndPopup.style.display = 'block';
}

const paddle = new Paddle();
const ball = new Ball();

// Target initializeGame structure
async function initializeGame() {
    await Promise.all([loadQuestions(), loadAllSounds()]);
    if (loadingScreen) loadingScreen.style.display = 'none';

    resetGame();
    gameLoop();
    console.log("Game start initiated automatically after loading.");

    // Global event listeners (keydown for game control, keyup, mousemove)
    // These are added once here and have internal checks (e.g., !quizActive, !gameIsOver)
    // to ensure they only act when appropriate.
    document.addEventListener('keydown', (event) => { 
        if (gameEndNavActive) {
            if (['Enter', 'Escape'].includes(event.key)) { 
                 event.preventDefault(); 
                if (gameEndPlayAgainButton) gameEndPlayAgainButton.click();
            }
            return; 
        }

        if (quizNavActive && currentQuestion) {
            const buttons = quizAnswersEl.getElementsByTagName('button');
            if (['ArrowDown', 'ArrowUp', 'Enter', 'Escape'].includes(event.key)) {
                event.preventDefault();
            }
            if (event.key === 'ArrowDown') {
                if (buttons.length > 0) {
                    selectedAnswerIndex = (selectedAnswerIndex + 1) % buttons.length;
                    updateQuizAnswerSelectionVisuals();
                }
            } else if (event.key === 'ArrowUp') {
                if (buttons.length > 0) {
                    selectedAnswerIndex = (selectedAnswerIndex - 1 + buttons.length) % buttons.length;
                    updateQuizAnswerSelectionVisuals();
                }
            } else if (event.key === 'Enter') {
                if (buttons.length > 0 && selectedAnswerIndex >= 0 && selectedAnswerIndex < buttons.length) {
                    if (!buttons[selectedAnswerIndex].disabled) { 
                        handleAnswer(selectedAnswerIndex);
                    }
                }
            } else if (event.key === 'Escape') { // Escape from Quiz
                endQuiz();
            }
            return; 
        }

        // Global Escape to hide game container if no popups are active
        if (event.key === 'Escape' && !quizActive && !gameEndNavActive && !gameIsOver) {
            if (gameContainer) gameContainer.style.display = 'none';
            gameIsOver = true; 
            return; 
        }
        
        // Paddle controls - only if game is active and no popups are shown
        if (!quizActive && !gameIsOver && !gameEndNavActive) { 
            if (event.key === "ArrowLeft") arrowLeftPressed = true;
            else if (event.key === "ArrowRight") arrowRightPressed = true;
        }
    });

    document.addEventListener('keyup', (event) => {
        if (event.key === "ArrowLeft") arrowLeftPressed = false;
        else if (event.key === "ArrowRight") arrowRightPressed = false;
    });

    document.addEventListener('mousemove', (event) => {
        if (quizActive || gameEndNavActive || gameIsOver) { 
            return; 
        }
        const rect = canvas.getBoundingClientRect();
        const mouseX = event.clientX - rect.left;
        paddle.x = mouseX - paddle.width / 2;

        if (paddle.x < 0) paddle.x = 0;
        if (paddle.x + paddle.width > canvas.width) paddle.x = canvas.width - paddle.width;
    });
    

}

function gameLoop() {
    update(); 
    drawGame(); 
    requestAnimationFrame(gameLoop);
}

// ----------- NEU: Steuerung für Startbildschirm und Spielstart ------------

const startScreen = document.getElementById('startScreen');
const startButton = document.getElementById('startButton');
if (gameContainer) gameContainer.style.display = 'none'; // Spiel-Canvas ausblenden

// Nur laden, nicht starten
async function preloadGameAssets() {
    loadQuestions();
    try {
        await loadAllSounds();
    } finally {
        if (loadingScreen) loadingScreen.style.display = 'none';
        if (startButton) startButton.disabled = false; // Button aktivieren!
    }
}
preloadGameAssets();

// Klick auf "Spiel und Quiz beginnen" startet das Spiel wirklich
if (startButton) {
    startButton.addEventListener('click', function () {
        if (startScreen) startScreen.style.display = 'none';
        if (gameContainer) gameContainer.style.display = 'block';
        initializeGame(); // Jetzt wirklich Spiel und Loop starten
    });
}
