from flask import Blueprint, render_template, session, redirect, url_for

html_bp = Blueprint('html', __name__)

@html_bp.route('/')
def index():
    return render_template('index.html')

@html_bp.route('/registration')
def registration():
    return render_template('registration.html')

@html_bp.route('/login')
def login():
    return render_template('login.html')

@html_bp.route('/products')
def products():
    if 'user_id' not in session:
        return redirect(url_for('html.login'))
    return render_template('products.html')

@html_bp.route('/cart')
def cart():
    if 'user_id' not in session:
        return redirect(url_for('html.login'))
    return render_template('cart.html')

@html_bp.route('/admin_login')
def admin_login():
    return render_template('admin_login.html')

@html_bp.route('/admin')
def admin():
    if 'admin_id' not in session:
        return redirect(url_for('html.admin_login'))
    return render_template('admin.html')

@html_bp.route('/api/generate_bill/<int:order_id>', methods=['GET'])
def generate_bill(order_id):
    from models import Order
    if 'user_id' not in session and 'admin_id' not in session:
        return "Unauthorized: Please log in to view bills.", 401
    try:
        order = Order.query.get(order_id)
        if not order:
            return "Order not found", 404
        if 'user_id' in session and 'admin_id' not in session:
            if order.user_id != session['user_id']:
                return "Unauthorized: You do not have permission to view this bill.", 403
        
        # Prepare data structured exactly as Jinja expects
        order_dict = {
            'order_id': order.order_id,
            'order_date': order.order_date,
            'total_amount': order.total_amount,
            'status': order.status,
            'username': order.user.username,
            'email': order.user.email
        }
        
        items_list = []
        for item in order.items:
            items_list.append({
                'p_name': item.product.p_name,
                'quantity': item.quantity,
                'price': item.product.price,
                'sum_amount': item.sum_amount
            })
            
        return render_template('invoice.html', order=order_dict, items=items_list)
    except Exception as e:
        return str(e), 500

